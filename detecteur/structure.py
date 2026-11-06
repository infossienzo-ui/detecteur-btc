"""Swings et structure (définitions du plan).

Swing high / low : bougie dont le plus haut (plus bas) dépasse les n bougies de chaque côté ; il n'est connu qu'à la
clôture de la n-ième bougie suivante (confirmation).
BOS : clôture au-delà du dernier swing dans le sens de la tendance. CHoCH : clôture au-delà du dernier swing opposé.
La tendance est le sens de la dernière cassure.
Jambe d'impulsion : de l'extrême situé entre le swing cassé et la cassure, jusqu'à l'extrême atteint depuis.

Tout est écrit pour le sens haussier ; le sens baissier s'obtient sur les prix retournés (vue « miroir »)."""
import numpy as np


def swings(h, l, n):
    N = len(h)
    sh, sl = np.zeros(N, bool), np.zeros(N, bool)
    if N > 2 * n:
        a, b = np.ones(N - 2 * n, bool), np.ones(N - 2 * n, bool)
        c_h, c_l = h[n:N - n], l[n:N - n]
        for k in range(1, n + 1):
            a &= (c_h > h[n - k:N - n - k]) & (c_h > h[n + k:N - n + k])
            b &= (c_l < l[n - k:N - n - k]) & (c_l < l[n + k:N - n + k])
        sh[n:N - n], sl[n:N - n] = a, b
    return sh, sl


def structure(h, l, c, sh, sl, n):
    """État à la clôture de chaque bougie t (sans information future)."""
    N = len(c)
    tr = np.zeros(N, np.int8)
    shl, shp = np.full(N, np.nan), np.full(N, -1)   # dernier swing high confirmé non cassé
    sll, slp = np.full(N, np.nan), np.full(N, -1)
    jd, jf, td, ev = (np.full(N, -1) for _ in range(4))  # jambe : début, fin ; début de la tendance ; dernière cassure
    evenements = []
    csh = csl = None
    T, JD, JF, TD, EV = 0, -1, -1, -1, -1
    for t in range(N):
        i = t - n
        if i >= n:
            if sh[i]:
                csh = (h[i], i)
            if sl[i]:
                csl = (l[i], i)
        if csh is not None and c[t] > csh[0]:
            s = csh[1]
            L = s + int(np.argmin(l[s:t + 1]))
            if T != 1:
                TD = L
            evenements.append({"t": t, "sens": 1, "type": "BOS" if T == 1 else "CHoCH", "niv": float(csh[0]), "piv": s, "jambe": L})
            T, JD, EV = 1, L, len(evenements) - 1
            JF = L + int(np.argmax(h[L:t + 1]))
            csh = None
        elif csl is not None and c[t] < csl[0]:
            s = csl[1]
            H = s + int(np.argmax(h[s:t + 1]))
            if T != -1:
                TD = H
            evenements.append({"t": t, "sens": -1, "type": "BOS" if T == -1 else "CHoCH", "niv": float(csl[0]), "piv": s, "jambe": H})
            T, JD, EV = -1, H, len(evenements) - 1
            JF = H + int(np.argmin(l[H:t + 1]))
            csl = None
        elif JF >= 0:
            if T == 1 and h[t] > h[JF]:
                JF = t
            elif T == -1 and l[t] < l[JF]:
                JF = t
        tr[t], jd[t], jf[t], td[t], ev[t] = T, JD, JF, TD, EV
        if csh is not None:
            shl[t], shp[t] = csh
        if csl is not None:
            sll[t], slp[t] = csl
    return {"tendance": tr, "sh_niv": shl, "sh_piv": shp, "sl_niv": sll, "sl_piv": slp,
            "jambe_deb": jd, "jambe_fin": jf, "tendance_deb": td, "cassure": ev, "evenements": evenements}
