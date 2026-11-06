"""Bougies BTCUSDT perp : historique H1 (fichier), mise à jour en direct (API publiques), timeframes reconstruits.

Toutes les heures sont en UTC dans le code ; l'affichage (Telegram, dashboard) est converti en heure de Paris.
Une bougie qui s'ouvre à T se clôture à T + durée : un timeframe supérieur n'est connu qu'à sa clôture."""
import json
import time
import urllib.request

import numpy as np
import pandas as pd

TF_REGLE = {"H1": "1h", "H2": "2h", "H3": "3h", "H4": "4h", "H6": "6h", "H8": "8h", "H12": "12h", "D": "1D"}
TF_HEURES = {"H1": 1, "H2": 2, "H3": 3, "H4": 4, "H5": 5, "H6": 6, "H8": 8, "H12": 12, "D": 24}
TF_ORDRE = ["H1", "H2", "H4", "H6", "H12", "D"]          # timeframes utilisés par la détection
TF_AFFICHAGE = ["M1", "M5", "M15", "M30", "H1", "H2", "H3", "H4", "H5", "H6", "H8", "H12", "D"]   # graphique
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30}
HEURE = np.int64(3600 * 10**9)


def charger_h1(chemin):
    k = pd.read_parquet(chemin)[["ts", "open", "high", "low", "close", "volume"]]
    k["ts"] = pd.to_datetime(k["ts"]).astype("datetime64[ns]")
    return grille_h1(k.set_index("ts"))


def grille_h1(k):
    k = k[~k.index.duplicated(keep="last")].sort_index()
    grille = pd.date_range(k.index.min(), k.index.max(), freq="h")
    p = k.reindex(grille)
    p["close"] = p["close"].ffill()
    for c in ("open", "high", "low"):
        p[c] = p[c].fillna(p["close"])
    p["volume"] = p["volume"].fillna(0.0)
    p.index.name = "ts"
    return p[["open", "high", "low", "close", "volume"]].astype(float)


def agreger(h1, tf):
    """Bougies complètes du timeframe (alignées sur 00:00 UTC). Colonne fin = heure de clôture.
    5h : 24 n'étant pas divisible par 5, les bougies repartent de 00:00 UTC chaque jour (00, 05, 10, 15, 20 h ; la dernière
    dure 4 h), comme le font les graphiques en séance continue."""
    if tf == "H1":
        out = h1.copy()
    elif tf == "H5":
        jour = h1.index.floor("D")
        cle = jour + pd.to_timedelta((h1.index.hour // 5) * 5, unit="h")
        g = h1.groupby(cle)
        out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        attendu = np.where(out.index.hour == 20, 4, 5)
        out = out[g["close"].count().to_numpy() == attendu]
        out["fin"] = out.index + pd.to_timedelta(attendu[g["close"].count().to_numpy() == attendu], unit="h")
        return out
    else:
        g = h1.resample(TF_REGLE[tf])
        out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        out = out[g["close"].count() == TF_HEURES[tf]]
    out["fin"] = out.index + pd.Timedelta(hours=TF_HEURES[tf])
    return out


# ----------------------------------------------------------------------------- mise à jour en direct

SOURCES = [
    # (nom, url, perp ?) — la première qui répond est utilisée ; les serveurs GitHub sont aux États-Unis,
    # où l'API futures de Binance est souvent bloquée.
    ("binance-perp", "https://fapi.binance.com/fapi/v1/klines?symbol={s}&interval=1h&limit={n}&startTime={t}", True),
    ("binance-spot-data", "https://data-api.binance.vision/api/v3/klines?symbol={s}&interval=1h&limit={n}&startTime={t}", False),
]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "detecteur-setups/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def telecharger_depuis(symbole, debut_ms, log=print):
    """Bougies H1 clôturées depuis debut_ms. Renvoie (DataFrame, source)."""
    for nom, url, _ in SOURCES:
        try:
            lignes, t = [], int(debut_ms)
            while True:
                lot = _get(url.format(s=symbole, n=1000, t=t))
                if not lot:
                    break
                lignes += lot
                t = int(lot[-1][0]) + 3600_000
                if len(lot) < 1000:
                    break
                time.sleep(0.2)
            if not lignes:
                return None, nom
            d = pd.DataFrame([r[:6] for r in lignes], columns=["ts", "open", "high", "low", "close", "volume"])
            d["ts"] = pd.to_datetime(d["ts"], unit="ms")
            d = d.set_index("ts").astype(float)
            maintenant = pd.Timestamp.utcnow().tz_localize(None)
            d = d[d.index + pd.Timedelta(hours=1) <= maintenant]  # bougies clôturées seulement
            return d, nom
        except Exception as e:  # noqa: BLE001
            log(f"   source {nom} indisponible : {e}")
    raise RuntimeError("Aucune source de prix accessible")
