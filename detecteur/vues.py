"""Une « vue » = un timeframe vu dans un sens. Le sens baissier est le sens haussier appliqué aux prix retournés
(prix → −prix) : chaque règle n'est écrite qu'une fois, pour le long. prix_origine = sens × prix_vue."""
import numpy as np

from . import indicateurs as ind
from .structure import swings, structure
from .donnees import TF_ORDRE

NOMS_MIROIR = {"VAH": "VAL", "VAL": "VAH", "PDL": "PDH", "PDH": "PDL", "Bas de range": "Haut de range",
               "Haut de range": "Bas de range"}


def nom_origine(nom, sens):
    return nom if sens > 0 else NOMS_MIROIR.get(nom, nom)


def bande_origine(lo, hi, sens):
    return (float(lo), float(hi)) if sens > 0 else (float(-hi), float(-lo))


class Vue:
    def __init__(self, df, tf, sens, cfg):
        g = cfg["general"]
        self.tf, self.sens, self.n = tf, sens, g["swing_n"]
        self.rang = TF_ORDRE.index(tf)
        self.deb = df.index.to_numpy().astype("datetime64[ns]").astype(np.int64)
        self.fin = df["fin"].to_numpy().astype("datetime64[ns]").astype(np.int64)
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        if sens < 0:
            o, h, l, c = -o, -l, -h, -c
        self.o, self.h, self.l, self.c = o, h, l, c
        self.v = df["volume"].to_numpy(float)
        self.N = len(c)
        periodes = sorted(set(g["emas"]) | set(g["ema_declencheurs"]) | {g["ema_lente"]})
        self.ema = {k: ind.ema(c, k) for k in periodes}
        self.ema_l = self.ema[g["ema_lente"]]
        self.ema_decl = [(f"EMA {k}", self.ema[k]) for k in g["ema_declencheurs"]]
        self.rsi = ind.rsi(c, g["rsi_periode"])
        self.atr = ind.atr(h, l, c, g["atr_periode"])
        self.sh, self.sl = swings(h, l, self.n)
        self.st = structure(h, l, c, self.sh, self.sl, self.n)
        self.hauts = np.flatnonzero(self.sh)
        self.bas = np.flatnonzero(self.sl)
        # bougies de rejet (sens haussier de la vue)
        rng = np.where(h - l > 0, h - l, np.nan)
        with np.errstate(invalid="ignore"):
            self.pinbar = (np.minimum(o, c) - l) / rng > cfg["strat1"]["pinbar_meche"]
        po, pc = np.r_[np.nan, o[:-1]], np.r_[np.nan, c[:-1]]
        self.englobante = (pc < po) & (c > o) & (c >= po) & (o <= pc)
        self.div, self.div_cachee = self._divergences(cfg["divergence"])
        self.profil = None
        self.zones_fixes = None

    # ------------------------------------------------------------------ divergences
    def _divergences(self, d):
        """Divergences RSI, règle classique, entre deux creux consécutifs (swings) écartés de ecart_min à ecart_max bougies ;
        confirmées à la clôture de la bougie qui confirme le second creux (i2 + n).
        Classique (haussière) : creux plus bas, RSI plus haut. Cachée (haussière) : creux plus haut, RSI plus bas.
        Sur la vue miroir, ce sont les divergences baissières (sommets) du prix d'origine."""
        reg, cach, b, l, r = {}, {}, self.bas, self.l, self.rsi
        for k in range(1, len(b)):
            i1, i2 = int(b[k - 1]), int(b[k])
            if not d["ecart_min"] <= i2 - i1 <= d["ecart_max"]:
                continue
            conf = i2 + self.n
            if l[i2] < l[i1] and r[i2] > r[i1]:
                reg[conf] = (i1, i2)
            elif l[i2] > l[i1] and r[i2] < r[i1]:
                cach[conf] = (i1, i2)
        return reg, cach

    # ------------------------------------------------------------------ zones fixes (OB, FVG)
    def calculer_zones_fixes(self, cfg):
        s1 = cfg["strat1"]
        zs = []
        o, h, l, c = self.o, self.h, self.l, self.c
        if s1["zones"]["OB"]:
            for ev in self.st["evenements"]:
                if ev["sens"] != 1:
                    continue
                L = ev["jambe"]
                for j in range(L, max(L - s1["ob_recherche"], -1), -1):
                    if c[j] < o[j]:
                        lo, hi = (min(o[j], c[j]), max(o[j], c[j])) if s1["ob_corps"] else (l[j], h[j])
                        zs.append({"type": "OB", "cree": ev["t"], "lo": lo, "hi": hi, "bougie": j})
                        break
        if s1["zones"]["FVG"]:
            with np.errstate(invalid="ignore"):
                ok = np.zeros(self.N, bool)
                ok[2:] = (l[2:] > h[:-2]) & ((l[2:] - h[:-2]) >= s1["fvg_min_atr"] * self.atr[2:])
            for i in np.flatnonzero(ok):
                zs.append({"type": "FVG", "cree": int(i), "lo": h[i - 2], "hi": l[i], "bougie": int(i - 1)})
        for z in zs:
            # FVG : comblé entièrement par une mèche (réglage de l'indicateur d'Enzo : wicks, full fill) ; OB : clôture au-delà
            serie = l if (z["type"] == "FVG" and s1["fvg_comble"] == "meches") else c
            k = np.flatnonzero(serie[z["cree"] + 1:] <= z["lo"]) if serie is l else np.flatnonzero(c[z["cree"] + 1:] < z["lo"])
            z["fin"] = int(z["cree"] + 1 + k[0]) if len(k) else self.N
        zs.sort(key=lambda z: z["cree"])
        self.zones_fixes = zs

    # ------------------------------------------------------------------ motifs (drapeau / wedge)
    def motif_descendant(self, t, p0):
        """Deux sommets descendants et deux creux descendants confirmés depuis la bougie p0 (canal ou wedge contre la
        tendance). Renvoie la droite des sommets (i_a, h_a, pente) ou None."""
        n = self.n
        H = self.hauts
        a, b = np.searchsorted(H, p0), np.searchsorted(H, t - n, "right")
        if b - a < 2:
            return None
        i1, i2 = H[b - 2], H[b - 1]
        if not self.h[i2] < self.h[i1]:
            return None
        L = self.bas
        a2, b2 = np.searchsorted(L, p0), np.searchsorted(L, t - n, "right")
        if b2 - a2 < 2:
            return None
        j1, j2 = L[b2 - 2], L[b2 - 1]
        if not self.l[j2] < self.l[j1]:
            return None
        return (int(i1), float(self.h[i1]), (self.h[i2] - self.h[i1]) / (i2 - i1), int(i2), int(j1), int(j2))

    @staticmethod
    def droite(m, t):
        return m[1] + m[2] * (t - m[0])


def construire_vues(tfs_df, cfg, tfs):
    vues = {}
    for sens in (1, -1):
        for tf in tfs:
            v = Vue(tfs_df[tf], tf, sens, cfg)
            if tf in ("H4", "H6", "D", "H12"):
                v.calculer_zones_fixes(cfg)
            vues[(sens, tf)] = v
    return vues


def profils_vue(prof_origine, sens):
    if sens > 0:
        return prof_origine
    return {"POC": -prof_origine["POC"][:, ::-1], "VAH": -prof_origine["VAL"][:, ::-1], "VAL": -prof_origine["VAH"][:, ::-1]}
