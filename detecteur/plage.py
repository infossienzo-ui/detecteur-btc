"""Range H4 (stratégie 2, « extrémité de range »).

Bornes : au moins 2 swings H4 hauts à moins de tol × ATR H4 l'un de l'autre (haut du range) et au moins 2 swings bas
(bas du range), trouvés dans la fenêtre de recherche. Le range dure au moins jours_min depuis la première touche, aucune
clôture H12 en dehors des bornes depuis cette touche, la dernière clôture H4 est à l'intérieur, et la largeur dépasse
largeur_min × ATR H4. Calculé à chaque clôture H4, en prix d'origine."""
import numpy as np

JOUR = np.int64(24 * 3600 * 10**9)


def _amas(pivs, nivs, tol):
    """Premier groupe (en partant du plus récent) d'au moins 2 niveaux à moins de tol de l'ancre."""
    for k in range(len(pivs) - 1, -1, -1):
        m = np.abs(nivs - nivs[k]) <= tol
        if m.sum() >= 2:
            return pivs[m], nivs[m]
    return None, None


def ranges_h4(v4, h12, cfg):
    """v4 : vue H4 dans le sens haussier (prix d'origine). h12 : DataFrame H12 (colonne fin)."""
    r = cfg["strat2"]["range"]
    n, N = v4.n, v4.N
    haut = np.full((N, 2), np.nan)
    bas = np.full((N, 2), np.nan)
    debut = np.full(N, -1)
    f12 = h12["fin"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    c12 = h12["close"].to_numpy(float)
    fen = int(r["fenetre_jours"] * 6)
    H, L = v4.hauts, v4.bas
    for e in range(N):
        a, b = np.searchsorted(H, e - fen), np.searchsorted(H, e - n, "right")
        a2, b2 = np.searchsorted(L, e - fen), np.searchsorted(L, e - n, "right")
        if b - a < 2 or b2 - a2 < 2:
            continue
        tol = r["tol_atr_h4"] * v4.atr[e]
        ph, nh = _amas(H[a:b][-8:], v4.h[H[a:b][-8:]], tol)
        pl, nl = _amas(L[a2:b2][-8:], v4.l[L[a2:b2][-8:]], tol)
        if ph is None or pl is None:
            continue
        top_lo, top_hi, bot_lo, bot_hi = nh.min(), nh.max(), nl.min(), nl.max()
        if top_lo - bot_hi < r["largeur_min_atr_h4"] * v4.atr[e]:
            continue
        d0 = int(min(ph.min(), pl.min()))
        if v4.fin[e] - v4.deb[d0] < r["jours_min"] * JOUR:
            continue
        if not (bot_lo <= v4.c[e] <= top_hi):
            continue
        g, d = np.searchsorted(f12, v4.deb[d0], "right"), np.searchsorted(f12, v4.fin[e], "right")
        if d > g and (c12[g:d].max() > top_hi or c12[g:d].min() < bot_lo):
            continue
        haut[e], bas[e], debut[e] = (top_lo, top_hi), (bot_lo, bot_hi), d0
    return {"haut": haut, "bas": bas, "debut": debut}
