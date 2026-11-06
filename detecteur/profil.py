"""Profil de volume (reproduit les réglages de l'outil d'Enzo) : période selon le timeframe (4h = 18 jours, D = 75 jours…),
20 niveaux, value area 70 %. Par défaut (source « barres »), le volume de chaque bougie du timeframe est réparti
uniformément entre son plus bas et son plus haut, comme le ferait un indicateur posé sur ce graphique ; la source « h1 »
répartit les bougies H1. Calculé à chaque clôture du timeframe. Volume : Binance perp seul."""
import numpy as np

HEURE = np.int64(3600 * 10**9)
JOUR = 24 * HEURE


def profil(lo, hi, v, niveaux=20, va=0.70):
    pmin, pmax = float(lo.min()), float(hi.max())
    if pmax <= pmin:
        pmax = pmin + 1e-9
    bords = np.linspace(pmin, pmax, niveaux + 1)
    eten = hi - lo
    recouv = np.clip(np.minimum(hi[:, None], bords[None, 1:]) - np.maximum(lo[:, None], bords[None, :-1]), 0, None)
    poids = recouv / np.where(eten > 0, eten, 1.0)[:, None]
    nuls = eten <= 0
    if nuls.any():
        k = np.clip(np.searchsorted(bords, lo[nuls], "right") - 1, 0, niveaux - 1)
        poids[nuls] = 0.0
        poids[np.flatnonzero(nuls), k] = 1.0
    vol = (poids * v[:, None]).sum(axis=0)
    poc = int(np.argmax(vol))
    cible, acc, a, b = va * vol.sum(), vol[poc], poc, poc
    while acc < cible and (a > 0 or b < niveaux - 1):
        haut = vol[b + 1] if b < niveaux - 1 else -1.0
        bas = vol[a - 1] if a > 0 else -1.0
        if haut >= bas:
            b += 1
            acc += haut
        else:
            a -= 1
            acc += bas
    return bords, vol, poc, b, a  # bords, volumes, rang POC, rang VAH, rang VAL


def fenetre(h1_deb, fin, jours):
    """Indices [g, d) des bougies H1 clôturées à fin, sur la période."""
    d = int(np.searchsorted(h1_deb, fin - HEURE, "right"))
    g = int(np.searchsorted(h1_deb, fin - jours * JOUR, "left"))
    return g, d


def profils_tf(h1, fins, jours, niveaux, va):
    """Bandes POC / VAH / VAL à chaque clôture du timeframe (prix d'origine). Renvoie dict de tableaux (N, 2)."""
    deb = h1.index.to_numpy().astype("datetime64[ns]").astype(np.int64)
    lo, hi, v = (h1[k].to_numpy(float) for k in ("low", "high", "volume"))
    N = len(fins)
    out = {k: np.full((N, 2), np.nan) for k in ("POC", "VAH", "VAL")}
    for e, f in enumerate(fins):
        g, d = fenetre(deb, f, jours)
        if d - g < 24:
            continue
        b, _, poc, vah, val = profil(lo[g:d], hi[g:d], v[g:d], niveaux, va)
        out["POC"][e] = b[poc], b[poc + 1]
        out["VAH"][e] = b[vah], b[vah + 1]
        out["VAL"][e] = b[val], b[val + 1]
    return out


def instantane(h1, fin, jours, niveaux, va):
    """Profil complet à un instant (pour le dessin du dashboard)."""
    deb = h1.index.to_numpy().astype("datetime64[ns]").astype(np.int64)
    g, d = fenetre(deb, fin, jours)
    lo, hi, v = (h1[k].to_numpy(float)[g:d] for k in ("low", "high", "volume"))
    b, vol, poc, vah, val = profil(lo, hi, v, niveaux, va)
    return {"bords": [round(float(x), 2) for x in b], "volumes": [round(float(x), 1) for x in vol],
            "poc": poc, "vah": vah, "val": val, "jours": jours}


def profils_barres(df, jours, niveaux, va):
    """Bandes POC / VAH / VAL à chaque clôture du timeframe, sur ses propres bougies des `jours` derniers jours."""
    deb = df.index.to_numpy().astype("datetime64[ns]").astype(np.int64)
    fins = df["fin"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    lo, hi, v = (df[k].to_numpy(float) for k in ("low", "high", "volume"))
    N = len(df)
    out = {k: np.full((N, 2), np.nan) for k in ("POC", "VAH", "VAL")}
    for e in range(N):
        g = int(np.searchsorted(deb, fins[e] - np.int64(jours * JOUR), "left"))
        if e + 1 - g < 5:
            continue
        b, _, poc, vah, val = profil(lo[g:e + 1], hi[g:e + 1], v[g:e + 1], niveaux, va)
        out["POC"][e] = b[poc], b[poc + 1]
        out["VAH"][e] = b[vah], b[vah + 1]
        out["VAL"][e] = b[val], b[val + 1]
    return out


def instantane_barres(df, e, jours, niveaux, va):
    deb = df.index.to_numpy().astype("datetime64[ns]").astype(np.int64)
    fins = df["fin"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    g = int(np.searchsorted(deb, fins[e] - np.int64(jours * JOUR), "left"))
    lo, hi, v = (df[k].to_numpy(float)[g:e + 1] for k in ("low", "high", "volume"))
    b, vol, poc, vah, val = profil(lo, hi, v, niveaux, va)
    return {"bords": [round(float(x), 2) for x in b], "volumes": [round(float(x), 1) for x in vol],
            "poc": poc, "vah": vah, "val": val, "jours": jours, "debut": int(deb[g] // 10**9)}
