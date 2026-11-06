"""Tâche horaire du détecteur (lancée par GitHub Actions 2 minutes après chaque heure pleine).

1. Ajoute les bougies 1h clôturées depuis la dernière vérification (Coinalyze, sinon Binance).
2. Applique les deux stratégies du plan sur tout l'historique.
3. Envoie sur Telegram les alertes apparues depuis la vérification précédente.
4. Prépare les données du dashboard (site/donnees), publié ensuite sur GitHub Pages.

Secrets lus dans l'environnement (jamais écrits dans les journaux) : COINALYZE_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID.
"""
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from detecteur import config as C, donnees, export_web  # noqa: E402
from detecteur.moteur import Moteur  # noqa: E402

NS = 10**9
HEURE = pd.Timedelta(hours=1)
PARIS = ZoneInfo("Europe/Paris")
FICHIER_BASE = RACINE / "data" / "klines_perp_1h_base.parquet"
DOSSIER_H1 = RACINE / "data" / "h1"
FICHIER_ETAT = RACINE / "etat" / "etat.json"
FICHIER_CONFIG = RACINE / "config.json"
DOSSIER_SITE = RACINE / "site" / "donnees"
SYMBOLE_CZ = "BTCUSDT_PERP.A"
INTERVALLES_CZ = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1hour"}
SECONDES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}
JOURS_BAS_TF = {"M1": 1, "M5": 4, "M15": 12, "M30": 25}
INTERVALLES_BN = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h"}


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------------------- état et configuration

def lire_json(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return defaut


def ecrire_json(chemin, d):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def charger_config():
    try:
        return C.charger(str(FICHIER_CONFIG))
    except Exception as e:  # noqa: BLE001
        log(f"⚠️ config.json illisible ({e}) : valeurs par défaut utilisées")
        return C.charger()


# ----------------------------------------------------------------------------- bougies

def charger_historique():
    base = pd.read_parquet(FICHIER_BASE)[["ts", "open", "high", "low", "close", "volume"]]
    base["ts"] = pd.to_datetime(base["ts"]).astype("datetime64[ns]")
    parts = [base.set_index("ts")]
    for f in sorted(DOSSIER_H1.glob("*.csv")):
        d = pd.read_csv(f, parse_dates=["ts"])
        d["ts"] = d["ts"].astype("datetime64[ns]")
        parts.append(d.set_index("ts")[["open", "high", "low", "close", "volume"]])
    k = pd.concat(parts)
    return k[~k.index.duplicated(keep="last")].sort_index()


def ajouter_csv(nouvelles):
    DOSSIER_H1.mkdir(parents=True, exist_ok=True)
    for mois, g in nouvelles.groupby(nouvelles.index.strftime("%Y-%m")):
        f = DOSSIER_H1 / f"{mois}.csv"
        g.reset_index().rename(columns={"index": "ts"}).to_csv(f, mode="a", header=not f.exists(), index=False)


def _get_json(url, headers=None, essais=4):
    req = urllib.request.Request(url, headers={"User-Agent": "detecteur-btc/1.0", **(headers or {})})
    for k in range(essais):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and k < essais - 1:
                time.sleep(int(e.headers.get("Retry-After", "5")) + 1)
                continue
            raise
        except urllib.error.URLError:
            if k < essais - 1:
                time.sleep(3)
                continue
            raise


def bougies_coinalyze(tf, debut, fin):
    cle = os.environ.get("COINALYZE_API_KEY")
    if not cle:
        raise RuntimeError("secret COINALYZE_API_KEY absent")
    pas = SECONDES[tf]
    t0, t1f = int(debut.timestamp()), int(fin.timestamp())
    lignes = []
    while t0 < t1f:
        t1 = min(t0 + 1900 * pas, t1f)
        q = urllib.parse.urlencode({"symbols": SYMBOLE_CZ, "interval": INTERVALLES_CZ[tf], "from": t0, "to": t1})
        for item in _get_json(f"https://api.coinalyze.net/v1/ohlcv-history?{q}", {"api_key": cle}):
            lignes += item.get("history", [])
        t0 = t1
        time.sleep(1.6)   # 40 appels par minute au plus
    if not lignes:
        return None
    d = pd.DataFrame(lignes).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    d["ts"] = pd.to_datetime(d["t"], unit="s")
    return d.drop_duplicates("ts").set_index("ts").sort_index()[["open", "high", "low", "close", "volume"]].astype(float)


def bougies_binance(tf, debut, fin, futures=True):
    hote = "https://fapi.binance.com/fapi/v1/klines" if futures else "https://data-api.binance.vision/api/v3/klines"
    t0, t1f = int(debut.timestamp() * 1000), int(fin.timestamp() * 1000)
    lignes = []
    while t0 < t1f:
        q = urllib.parse.urlencode({"symbol": "BTCUSDT", "interval": INTERVALLES_BN[tf], "startTime": t0, "endTime": t1f, "limit": 1000})
        lot = _get_json(f"{hote}?{q}")
        if not lot:
            break
        lignes += lot
        t0 = int(lot[-1][0]) + SECONDES[tf] * 1000
        if len(lot) < 1000:
            break
    if not lignes:
        return None
    d = pd.DataFrame([r[:6] for r in lignes], columns=["t", "open", "high", "low", "close", "volume"])
    d["ts"] = pd.to_datetime(d["t"], unit="ms")
    return d.drop_duplicates("ts").set_index("ts").sort_index()[["open", "high", "low", "close", "volume"]].astype(float)


SOURCES = [("Coinalyze · Binance perp", lambda tf, a, b: bougies_coinalyze(tf, a, b)),
           ("Binance perp", lambda tf, a, b: bougies_binance(tf, a, b, True)),
           ("Binance spot (perp indisponible)", lambda tf, a, b: bougies_binance(tf, a, b, False))]


def _utc(t):
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def recuperer(tf, debut, fin, perp_seulement=False):
    """Première source qui répond. Renvoie (DataFrame des bougies clôturées, index UTC sans fuseau ; nom de la source).
    perp_seulement : jamais de bougies spot (l'historique du détecteur ne doit contenir que le perp)."""
    debut, fin = _utc(debut), _utc(fin)
    for nom, f in (SOURCES[:2] if perp_seulement else SOURCES):
        try:
            d = f(tf, debut, fin)
            if d is not None and len(d):
                if d.index.tz is not None:
                    d.index = d.index.tz_convert(None)
                d = d[d.index + pd.Timedelta(seconds=SECONDES[tf]) <= fin.tz_convert(None)]
                return d, nom
        except Exception as e:  # noqa: BLE001
            log(f"   {nom} ({tf}) indisponible : {str(e)[:160]}")
    return None, None


def mettre_a_jour_h1(hist, etat, maintenant):
    """Ajoute les bougies 1h clôturées manquantes. Le volume de Coinalyze est remis à l'échelle de celui de Binance."""
    dernier = hist.index.max()
    debut = dernier - pd.Timedelta(hours=72)
    d, source = recuperer("H1", debut, maintenant, perp_seulement=True)
    if d is None:
        return hist, None, etat.get("facteur_volume", 1.0)
    facteur = etat.get("facteur_volume", 1.0)
    commun = hist.join(d, how="inner", rsuffix="_n")
    commun = commun[(commun["volume"] > 0) & (commun["volume_n"] > 0)]
    if len(commun) >= 12:
        facteur = float(np.median(commun["volume"] / commun["volume_n"]))
    nouvelles = d[d.index > dernier].copy()
    nouvelles["volume"] = nouvelles["volume"] * facteur
    if len(nouvelles):
        ajouter_csv(nouvelles.round({"open": 2, "high": 2, "low": 2, "close": 2, "volume": 3}))
        hist = pd.concat([hist, nouvelles])
    log(f"   {len(nouvelles)} bougie(s) 1h ajoutée(s) · source {source} · facteur de volume {facteur:.4f}")
    return hist, source, facteur


# ----------------------------------------------------------------------------- Telegram

NOMS_TF = {"H1": "1h", "H2": "2h", "H4": "4h", "H6": "6h", "H12": "12h", "D": "D"}
NOMS_STRAT = {1: "Continuation", 2: "Retournement"}


def quand(ts_s):
    t = pd.Timestamp(ts_s, unit="s", tz="UTC").tz_convert(PARIS)
    jours = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
    return f"{jours[t.weekday()]} {t:%d/%m} {t:%H}h"


def nom_zone(z):
    if z["type"] == "Fibo" and z.get("niveau"):
        n = z["niveau"]
        nom = f"Golden zone {n[0]}–{n[1]}" if len(n) == 2 else f"Fibo {n[0]}"
        return nom.replace(".", ",") + f" {NOMS_TF.get(z['tf'], z['tf'])}"
    return f"{z['type']} {NOMS_TF.get(z['tf'], z['tf'])}"


def message(a, url):
    tete = "🟢 <b>Setup détecté</b> — BTC" if a["niveau"] == "setup" else "🟡 <b>En préparation</b> — BTC"
    sens = "LONG" if a["sens"] == "long" else "SHORT"
    l2 = f"{NOMS_STRAT[a['strategie']]} (S{a['strategie']}) · {sens}" + (f" · grade {a['grade']}" if a["niveau"] == "setup" else "")
    decl = " + ".join(d["nom"].replace(" — en attente du déclencheur", "").replace(" — en attente du retest", " (attente du retest)")
                      for d in a["declencheurs"])
    l3 = f"{decl} · {NOMS_TF.get(a['tf'], a['tf'])} · clôture {quand(a['heure'])}"
    l4 = "Zone : " + " + ".join(nom_zone(z) for z in a["zones"])
    notes = "".join(f"\n• {n}" for n in a.get("notes", []))
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return f"{tete}\n{esc(l2)}\n{esc(l3)}\n{esc(l4)}{esc(notes)}\n<a href=\"{url}#{a['id']}\">→ Voir le graphique</a>"


def telegram(texte):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        log("   Telegram non configuré (secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID) : message non envoyé")
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": texte, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=20) as r:
            return json.loads(r.read().decode()).get("ok", False)
    except urllib.error.HTTPError as e:
        log(f"   Telegram a refusé le message ({e.code}) : {e.read().decode()[:200]}")
    except Exception as e:  # noqa: BLE001
        log(f"   Telegram injoignable : {str(e)[:160]}")
    return False


# ----------------------------------------------------------------------------- programme

def main():
    maintenant = pd.Timestamp.now(tz="UTC").floor("min")
    etat = lire_json(FICHIER_ETAT, {})
    cfg = charger_config()
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    url = os.environ.get("SITE_URL") or (f"https://{depot.split('/')[0]}.github.io/{depot.split('/')[1]}/" if "/" in depot else "")
    log(f"Vérification du {maintenant:%Y-%m-%d %H:%M} UTC")

    hist = charger_historique()
    hist, source, facteur = mettre_a_jour_h1(hist, etat, maintenant)
    h1 = donnees.grille_h1(hist)
    fin_ns = int((h1.index[-1] + HEURE).value)
    log(f"   historique 1h : {h1.index[0]:%Y-%m-%d} → {h1.index[-1] + HEURE:%Y-%m-%d %H:%M} UTC")

    t0 = time.time()
    M = Moteur(h1, cfg, log=lambda *a: None)
    debut = h1.index[-1] - pd.Timedelta(days=400)
    alertes = M.executer(debut=debut.value)
    log(f"   moteur : {len(alertes)} alertes sur 400 jours en {time.time() - t0:.0f} s")

    # alertes à envoyer : apparues depuis la vérification précédente (6 h au plus, pour ne jamais inonder)
    dernier = etat.get("dernier_tau")
    seuil = fin_ns - 6 * 3600 * NS if dernier else fin_ns - 1
    envoyees = set(etat.get("envoyees", []))
    a_envoyer = [a for a in alertes if a["tau"] > max(dernier or 0, seuil) and not a.get("filtree_rr")]
    if not etat.get("telegram_ok"):
        if telegram(f"✅ <b>Détecteur BTC en ligne</b>\nTu recevras ici les setups détectés.\n<a href=\"{url}\">Ouvrir le dashboard</a>"):
            etat["telegram_ok"] = True
    nb = 0
    for al in sorted(a_envoyer, key=lambda x: x["tau"]):
        a = M.exporter(al, avec_profil=False)
        if a["id"] in envoyees:
            continue
        if telegram(message(a, url)):
            envoyees.add(a["id"])
            nb += 1
    log(f"   {nb} alerte(s) envoyée(s) sur Telegram")

    # bougies 1m à 30m pour le graphique (non conservées dans le dépôt)
    bas, sources_bas = {}, {}
    for tf, j in JOURS_BAS_TF.items():
        d, s = recuperer(tf, maintenant - pd.Timedelta(days=j), maintenant)
        if d is not None:
            if s and s.startswith("Coinalyze"):
                d["volume"] = d["volume"] * facteur
            bas[tf], sources_bas[tf] = d, s
    freq = export_web.frequence(alertes, int(debut.value), fin_ns)
    meta = {"maquette": False, "derniere_verification": int(maintenant.value // NS), "depot": depot, "url": url,
            "source": source or "aucune source perp joignable à cette vérification (historique inchangé)",
            "sources_bas_tf": sources_bas, "cle_coinalyze": bool(os.environ.get("COINALYZE_API_KEY")),
            "telegram": bool(os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
            "message_absents": "Bougies indisponibles à cette vérification : la source n'a pas répondu."}
    export_web.ecrire_tout(M, alertes, int((h1.index[-1] - pd.Timedelta(days=365)).value), fin_ns, cfg, freq,
                           str(DOSSIER_SITE), meta["source"], meta_extra=meta, bas_tf=bas)
    log(f"   dashboard : {len(list(DOSSIER_SITE.glob('*.json')))} fichiers de données · timeframes 1m–30m : {sorted(bas)}")

    etat.update({"dernier_tau": fin_ns, "envoyees": sorted(envoyees)[-800:], "facteur_volume": facteur,
                 "derniere_verification": f"{maintenant:%Y-%m-%d %H:%M} UTC", "source": source})
    ecrire_json(FICHIER_ETAT, etat)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
