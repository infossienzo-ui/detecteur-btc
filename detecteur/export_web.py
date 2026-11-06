"""Données du dashboard (dossier donnees/) :
- alertes.json : alertes, fréquence des alertes, paramètres et leur description ;
- bougies_<TF>.json : bougies d'un timeframe d'affichage, avec EMA et RSI (chargé quand on choisit ce timeframe)."""
import json
import os

import numpy as np
import pandas as pd

from . import indicateurs as ind
from .config import SCHEMA
from .donnees import agreger, TF_AFFICHAGE, TF_MINUTES

NS = 10**9
FENETRE_JOURS = {"H1": 400, "H2": 420, "H3": 450, "H4": 500, "H5": 550, "H6": 600, "H8": 700, "H12": 900, "D": 1500}


def bougies_tf(h1, tf, cfg, fin_ns):
    return bougies_df(agreger(h1, tf), tf, cfg, fin_ns)


def bougies_df(df, tf, cfg, fin_ns=None):
    """Bougies d'un DataFrame (index = ouverture UTC) avec EMA et RSI, au format du dashboard."""
    c = df["close"].to_numpy(float)
    g = cfg["general"]
    emas = [ind.ema(c, k) for k in g["emas"]]
    rsi = ind.rsi(c, g["rsi_periode"])
    deb = df.index.to_numpy().astype("datetime64[ns]").astype(np.int64)
    a = 0 if fin_ns is None or tf not in FENETRE_JOURS else int(np.searchsorted(deb, fin_ns - FENETRE_JOURS[tf] * 86400 * NS))
    o, h, l, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "volume"))
    rows = []
    for i in range(a, len(df)):
        rows.append([int(deb[i] // NS), round(o[i], 1), round(h[i], 1), round(l[i], 1), round(c[i], 1), round(v[i], 0)]
                    + [round(x[i], 1) for x in emas] + [round(rsi[i], 1)])
    return {"tf": tf, "colonnes": ["t", "o", "h", "l", "c", "v"] + [f"ema{k}" for k in g["emas"]] + ["rsi"], "lignes": rows}


def _compte(x, semaines):
    return {"n": len(x), "par_semaine": round(len(x) / semaines, 1) if semaines else None}


def frequence(alertes, debut_ns, fin_ns):
    semaines = (fin_ns - debut_ns) / (7 * 86400 * NS)
    blocs = []
    for strat in (1, 2):
        lignes = []
        for niv, nom in (("setup", "🟢 Setups"), ("prepa", "🟡 Pré-alertes")):
            x = [a for a in alertes if a["strat"] == strat and a["niveau"] == niv and not a.get("filtree_rr")]
            lignes.append({"nom": nom, **_compte(x, semaines), "titre": True})
            if niv == "setup":
                for sens, ns in ((1, "Long"), (-1, "Short")):
                    lignes.append({"nom": ns, **_compte([a for a in x if a["sens"] == sens], semaines)})
                for gr in ("A", "B"):
                    y = [a for a in x if a["grade"] == gr]
                    if y:
                        lignes.append({"nom": f"Grade {gr}", **_compte(y, semaines)})
                for n in sorted({d["nom"] for a in x for d in a["declencheurs"]}):
                    lignes.append({"nom": f"Déclencheur : {n}", **_compte([a for a in x if any(d["nom"] == n for d in a["declencheurs"])], semaines)})
                for tf in ("H1", "H2", "H4"):
                    y = [a for a in x if a["tf"] == tf]
                    if y:
                        lignes.append({"nom": f"Timeframe {tf}", **_compte(y, semaines)})
                if strat == 1:
                    for f in ("OB", "FVG", "Fibo", "Profil", "EMA50"):
                        y = [a for a in x if f in a["familles"]]
                        if y:
                            lignes.append({"nom": f"Zone : {f}", **_compte(y, semaines)})
            else:
                for n in sorted({d["nom"] for a in x for d in a["declencheurs"]}):
                    lignes.append({"nom": n, **_compte([a for a in x if any(d["nom"] == n for d in a["declencheurs"])], semaines)})
        blocs.append({"strategie": strat, "lignes": lignes})
    return {"debut": int(debut_ns // NS), "fin": int(fin_ns // NS), "semaines": round(semaines, 1), "blocs": blocs}


def ecrire_tout(moteur, alertes, depuis_ns, fin_ns, cfg, freq, dossier, source, meta_extra=None, bas_tf=None):
    """bas_tf : {"M1": DataFrame, ...} bougies 1m à 30m récupérées en direct (absentes de la maquette)."""
    os.makedirs(dossier, exist_ok=True)
    bas_tf = bas_tf or {}
    sel = [a for a in alertes if a["tau"] >= depuis_ns]
    meta = {"genere": int(pd.Timestamp.utcnow().value // NS), "donnees_jusqu_a": int(fin_ns // NS), "source": source,
            "symbole": cfg["general"]["symbole"], "maquette": True,
            "tf_affichage": TF_AFFICHAGE, "tf_absents": [tf for tf in TF_MINUTES if tf not in bas_tf],
            "message_absents": "La maquette n'a que l'historique 1h du Drive. En ligne, les bougies 1m à 30m viennent directement de l'API."}
    meta.update(meta_extra or {})
    base = {"meta": meta, "alertes": [moteur.exporter(a) for a in sel], "frequence": freq, "config": cfg,
            "schema": [{"groupe": g, "champs": [{"chemin": c, "libelle": l, "type": t, "aide": h} for (c, l, t, h) in ch]}
                       for g, ch in SCHEMA]}
    tailles = {}
    with open(os.path.join(dossier, "alertes.json"), "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, separators=(",", ":"))
    tailles["alertes"] = os.path.getsize(os.path.join(dossier, "alertes.json"))
    # petit fichier relu par la page toutes les deux minutes : elle ne recharge alertes.json que s'il a changé
    with open(os.path.join(dossier, "version.json"), "w", encoding="utf-8") as f:
        json.dump({"genere": meta["genere"], "donnees_jusqu_a": meta["donnees_jusqu_a"]}, f)
    for tf in TF_AFFICHAGE:
        if tf in TF_MINUTES:
            if tf not in bas_tf:
                continue
            d = bougies_df(bas_tf[tf], tf, cfg)
        else:
            d = bougies_tf(moteur.h1, tf, cfg, fin_ns)
        chemin = os.path.join(dossier, f"bougies_{tf}.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(d, f, separators=(",", ":"))
        tailles[tf] = os.path.getsize(chemin)
    return base, tailles
