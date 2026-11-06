"""Moteur : à chaque clôture H1 (l'heure d'exécution), on regarde les timeframes de déclencheur qui viennent de clôturer
et on applique les deux stratégies du plan, dans les deux sens. Rien n'utilise une bougie non clôturée, sauf la note
« mèche en cours » des pré-alertes (bougie H4 en cours, dite comme telle).

Toutes les règles sont écrites pour le long, sur la vue du sens (prix retournés pour le short)."""
import numpy as np

from .donnees import agreger, TF_ORDRE, HEURE
from .vues import construire_vues, profils_vue, nom_origine, bande_origine
from .profil import profils_tf, instantane, profils_barres, instantane_barres
from .plage import ranges_h4

NS = 10**9


def rang(tf):
    return TF_ORDRE.index(tf)


class Moteur:
    def __init__(self, h1, cfg, log=print):
        self.cfg, self.h1, self.log = cfg, h1, log
        self.df = {tf: agreger(h1, tf) for tf in TF_ORDRE}
        self.vues = construire_vues(self.df, cfg, TF_ORDRE)
        tfp = set(cfg["strat1"]["tf_contexte"]) | set(cfg["strat2"]["zones_htf"]["profil_tf"]) | {"H4"}
        p = cfg["profil"]
        if p.get("source", "barres") == "barres":
            self.prof_o = {tf: profils_barres(self.df[tf], p["jours"][tf], p["niveaux"], p["value_area"]) for tf in tfp}
        else:
            self.prof_o = {tf: profils_tf(h1, self.vues[(1, tf)].fin, p["jours"][tf], p["niveaux"], p["value_area"]) for tf in tfp}
        self.prof = {(s, tf): profils_vue(self.prof_o[tf], s) for tf in tfp for s in (1, -1)}
        self.rng = ranges_h4(self.vues[(1, "H4")], self.df["H12"], cfg)
        self.suivi_zones = {}
        log(f"   moteur prêt : {len(h1)} bougies H1, profils {sorted(tfp)}, "
            f"{int((self.rng['debut'] >= 0).sum())} clôtures H4 en range")

    # ------------------------------------------------------------------ outils
    def idx(self, tf, tau):
        return int(np.searchsorted(self.vues[(1, tf)].fin, tau, "right")) - 1

    def idx_exact(self, tf, tau):
        f = self.vues[(1, tf)].fin
        t = int(np.searchsorted(f, tau))
        return t if t < len(f) and f[t] == tau else -1

    def zones_s1(self, s, E, e):
        """Zones actives de la stratégie 1 sur le timeframe E à la clôture e (vue du sens s)."""
        V, s1 = self.vues[(s, E)], self.cfg["strat1"]
        cle = (s, E)
        st = self.suivi_zones.setdefault(cle, {"p": 0, "actives": []})
        zs = V.zones_fixes
        while st["p"] < len(zs) and zs[st["p"]]["cree"] <= e:
            st["actives"].append(zs[st["p"]])
            st["p"] += 1
        st["actives"] = [z for z in st["actives"] if z["fin"] > e]
        td = V.st["tendance_deb"][e]
        out, compte = [], {}
        for z in reversed(st["actives"]):
            if z["cree"] < td:
                continue
            compte[z["type"]] = compte.get(z["type"], 0) + 1
            if compte[z["type"]] <= s1["zones_max_par_type"]:
                out.append({"type": z["type"], "tf": E, "lo": z["lo"], "hi": z["hi"], "debut": int(V.deb[z["bougie"]]),
                            "cle": f"{z['type']}-{E}-{z['bougie']}",
                            # pour le dessin seulement (information postérieure à l'alerte) : bougie qui a cassé / comblé la zone
                            "fin": int(V.deb[z["fin"]]) if z["fin"] < V.N else None})
        jd, jf = V.st["jambe_deb"][e], V.st["jambe_fin"][e]
        if s1["zones"]["Fibo"] and jd >= 0 and jf > jd:
            # chaque niveau est une zone fine (± épaisseur × ATR), sauf la golden zone qui est la bande entre ses deux niveaux
            L, H = V.l[jd], V.h[jf]
            meta = {"debut_t": int(V.deb[jd]), "debut_p": L, "fin_t": int(V.deb[jf]), "fin_p": H}
            g0, g1 = sorted(s1["fibo_golden"])
            ep = s1["fibo_epaisseur_atr"] * V.atr[e]
            for r in s1["fibo_niveaux"]:
                if g0 <= r <= g1:
                    continue
                p = H - r * (H - L)
                out.append({"type": "Fibo", "tf": E, "lo": p - ep, "hi": p + ep, "debut": int(V.deb[jd]),
                            "cle": f"Fibo-{E}-{jd}-{r}", "niveau": [r], "fibo": meta})
            out.append({"type": "Fibo", "tf": E, "lo": H - g1 * (H - L), "hi": H - g0 * (H - L), "debut": int(V.deb[jd]),
                        "cle": f"Fibo-{E}-{jd}-golden", "niveau": [g0, g1], "fibo": meta})
        if s1["zones"]["EMA50"]:
            k = s1["ema_zone_atr"] * V.atr[e]
            out.append({"type": "EMA50", "tf": E, "lo": V.ema_l[e] - k, "hi": V.ema_l[e] + k, "debut": None, "cle": f"EMA50-{E}"})
        if s1["zones"]["Profil"] and (s, E) in self.prof:
            P = self.prof[(s, E)]
            for nom in ("POC", "VAH", "VAL"):
                lo, hi = P[nom][e]
                if not np.isnan(lo):
                    out.append({"type": nom, "tf": E, "lo": lo, "hi": hi, "debut": None, "cle": f"{nom}-{E}"})
        return out

    @staticmethod
    def famille(z):
        return "Profil" if z["type"] in ("POC", "VAH", "VAL") else z["type"]

    # ------------------------------------------------------------------ passage complet
    def executer(self, debut=None, fin=None):
        cfg = self.cfg
        v1 = self.vues[(1, "H1")]
        taus = v1.fin
        a = 0 if debut is None else int(np.searchsorted(taus, np.int64(debut)))
        b = len(taus) if fin is None else int(np.searchsorted(taus, np.int64(fin), "right"))
        self.alertes, self.actives, self.suivi_zones = [], [], {}
        self.attente_s1 = {}   # (s, T) -> cassures de drapeau en attente du retest
        self.attente_s2 = {}   # (s, T) -> sweeps en attente du déclencheur
        tfd = sorted(set(cfg["strat1"]["tf_declencheurs"]) | set(cfg["strat2"]["tf_declencheurs"]), key=rang, reverse=True)
        for k in range(a, b):
            tau = int(taus[k])
            self._suivre(tau, k)
            for s in (1, -1):
                for T in tfd:
                    t = self.idx_exact(T, tau)
                    if t < 60:
                        continue
                    if cfg["strat2"]["actif"] and T in cfg["strat2"]["tf_declencheurs"]:
                        self._strat2(s, T, t, tau)
                    if cfg["strat1"]["actif"] and T in cfg["strat1"]["tf_declencheurs"]:
                        self._strat1(s, T, t, tau)
        return self.alertes

    # ------------------------------------------------------------------ alertes, doublons, suivi
    def _chevauche(self, strat, s, bande, niveaux):
        for a in self.actives:
            if a["strat"] == strat and a["sens"] == s and a["niveau"] in niveaux and a["statut"] == "en cours":
                if a["bande"][0] <= bande[1] and bande[0] <= a["bande"][1]:
                    return True
        return False

    def _emettre(self, al):
        cfg = self.cfg
        if al["niveau"] == "setup":
            filtre = cfg[f"strat{al['strat']}"]["filtre_rr"]
            al["filtree_rr"] = bool(filtre["actif"] and not al["rr_ok"])
            if al["filtree_rr"]:
                al["statut"] = "filtrée (R:R)"
                self.alertes.append(al)
                return
            if self._chevauche(al["strat"], al["sens"], al["bande"], ("setup",)):
                return
            for a in self.actives:   # la pré-alerte correspondante devient un setup
                if a["strat"] == al["strat"] and a["sens"] == al["sens"] and a["niveau"] == "prepa" and a["statut"] == "en cours" \
                        and a["bande"][0] <= al["bande"][1] and al["bande"][0] <= a["bande"][1]:
                    a["statut"] = "devenue setup"
            al["statut"] = "en cours"
            al["expire"] = al["tau"] + cfg["alertes"]["suivi_jours"] * 24 * HEURE
        else:
            if not cfg["pre_alertes"]["actif"] or self._chevauche(al["strat"], al["sens"], al["bande"], ("setup", "prepa")):
                return
            al["statut"] = "en cours"
            al["expire"] = al["tau"] + cfg["alertes"]["pre_alerte_heures"] * HEURE
        self.alertes.append(al)
        self.actives.append(al)

    def _suivre(self, tau, k):
        """Suivi des alertes en cours avec la bougie H1 qui clôture à tau : TP1 touché, invalidation à la clôture du
        timeframe d'étude, ou expiration."""
        reste = []
        for a in self.actives:
            if a["statut"] != "en cours":
                continue
            if a["niveau"] == "prepa":
                if tau >= a["expire"]:
                    a["statut"] = "expirée"
                else:
                    reste.append(a)
                continue
            vh = self.vues[(a["sens"], "H1")]
            ent, sl, risque = a["entree"], a["sl"], a["risque"]
            # sans niveaux automatiques, une alerte reste « active » (anti-doublon) jusqu'à la cassure de sa zone ou l'expiration
            if self.cfg["niveaux"]["auto"] and a["tp1"] is not None and vh.h[k] >= a["tp1"]:
                a["statut"], a["r"], a["clos"] = "TP1", a["rr"], tau
                continue
            ti = self.idx_exact(a["tf_inval"], tau)
            if ti >= 0 and self.vues[(a["sens"], a["tf_inval"])].c[ti] < sl:
                a["statut"], a["clos"] = "invalidée", tau
                a["r"] = float((self.vues[(a["sens"], a["tf_inval"])].c[ti] - ent) / risque)
                continue
            if tau >= a["expire"]:
                a["statut"], a["clos"] = "expirée", tau
                a["r"] = float((vh.c[k] - ent) / risque)
                continue
            reste.append(a)
        self.actives = reste

    # ------------------------------------------------------------------ TP de la stratégie 1
    def _tp1_s1(self, s, tau, entree):
        V = self.vues[(s, "H4")]
        e = self.idx("H4", tau)
        H = V.hauts[V.hauts <= e - V.n]
        for i in H[::-1][:30]:
            if V.h[i] > entree:
                return float(V.h[i]), int(V.deb[i])
        return None, None

    # ------------------------------------------------------------------ stratégie 1 : continuation
    def _strat1(self, s, T, t, tau):
        cfg, s1 = self.cfg, self.cfg["strat1"]
        dcl = s1["declencheurs"]
        VT = self.vues[(s, T)]
        ctx = []
        for E in s1["tf_contexte"]:
            if rang(E) < rang(T):
                continue
            VE = self.vues[(s, E)]
            e = self.idx(E, tau)
            if e < 60:
                continue
            if VE.st["tendance"][e] == 1 and VE.c[e] > VE.ema_l[e]:
                ctx.append((E, e, self.zones_s1(s, E, e)))
        Z = [z for (_, _, zs) in ctx for z in zs]

        def contient(p):
            return [z for z in Z if z["lo"] <= p <= z["hi"]]

        trouves = []
        cle = (s, T)
        tol = cfg["drapeau"]["retest_tol_atr"] * VT.atr[t]
        # retests en attente (cassure de drapeau déjà faite)
        garde = []
        for p in self.attente_s1.get(cle, []):
            lv = VT.droite(p["motif"], t)
            if t > p["t"] + cfg["drapeau"]["retest_barres"]:
                continue
            if VT.l[t] <= lv + tol:
                if VT.c[t] > lv and ctx:
                    trouves.append({"nom": "Cassure du drapeau (retest)", "zones": p["zones"],
                                    "dessin": dict(p["dessin"], retest_t=int(VT.deb[t]))})
                continue
            garde.append(p)
        self.attente_s1[cle] = garde
        if not ctx:
            return
        c = VT.c[t]
        Zc = contient(c)
        if Zc and dcl["reclaim"]:
            zr = [z for z in Zc if VT.l[t] < z["lo"]]
            if zr:
                niv = VT.st["sl_niv"][t - 1]
                liq = (not np.isnan(niv)) and VT.l[t] < niv
                emas = [nm for nm, arr in VT.ema_decl if VT.l[t] <= arr[t] < c]
                if liq or emas:
                    d = {"emas": emas}
                    if liq:
                        d["liquidite"] = {"niv": float(niv), "piv_t": int(VT.deb[VT.st["sl_piv"][t - 1]])}
                    trouves.append({"nom": "Reclaim", "zones": zr, "dessin": d})
        if Zc and dcl["rejet"] and (VT.englobante[t] or VT.pinbar[t]):
            trouves.append({"nom": "Bougie de rejet", "zones": Zc,
                            "dessin": {"forme": "englobante" if VT.englobante[t] else "pin bar"}})
        if Zc and dcl["reprise_ema"] and rang(T) >= rang(s1["reprise_ema_tf_min"]):
            x = [nm for nm, arr in VT.ema_decl if VT.c[t - 1] < arr[t - 1] and c > arr[t]]
            if x:
                trouves.append({"nom": "Reprise de l'EMA", "zones": Zc, "dessin": {"emas": x}})
        for cle_d, dico, nom_d in (("divergence", VT.div, "Divergence RSI"), ("divergence_cachee", VT.div_cachee, "Divergence RSI cachée")):
            if dcl[cle_d] and t in dico:
                i1, i2 = dico[t]
                zd = contient(VT.c[i2])
                if zd:
                    trouves.append({"nom": nom_d, "zones": zd, "dessin": {
                        "p1": {"t": int(VT.deb[i1]), "p": float(VT.l[i1]), "rsi": float(VT.rsi[i1])},
                        "p2": {"t": int(VT.deb[i2]), "p": float(VT.l[i2]), "rsi": float(VT.rsi[i2])}}})
        if dcl["drapeau"]:
            p0 = max((int(np.searchsorted(VT.deb, self.vues[(s, E)].deb[self.vues[(s, E)].st["jambe_fin"][e]]))
                      for (E, e, _) in ctx if self.vues[(s, E)].st["jambe_fin"][e] >= 0), default=None)
            m = VT.motif_descendant(t, p0) if p0 is not None else None
            if m is not None and c > VT.droite(m, t) and VT.c[t - 1] <= VT.droite(m, t - 1) and Zc:
                dessin = {"a": {"t": int(VT.deb[m[0]]), "p": m[1]}, "b": {"t": int(VT.deb[m[3]]), "p": float(VT.h[m[3]])},
                          "cassure": {"t": int(VT.deb[t]), "p": float(VT.droite(m, t))}}
                if cfg["drapeau"]["alerte"] == "cassure":
                    trouves.append({"nom": "Cassure du drapeau", "zones": Zc, "dessin": dessin})
                else:
                    self.attente_s1.setdefault(cle, []).append({"t": t, "motif": m, "zones": Zc, "dessin": dessin})
                    if cfg["pre_alertes"]["cassure_attente_retest"]:
                        self._emettre(self._alerte_s1(s, T, t, tau, ctx, [{"nom": "Cassure du drapeau — en attente du retest",
                                                                             "zones": Zc, "dessin": dessin}], "prepa"))
        if trouves:
            self._emettre(self._alerte_s1(s, T, t, tau, ctx, trouves, "setup"))
        elif T == "H1" and cfg["pre_alertes"]["prix_dans_zone"]:
            touche = [z for z in Z if VT.l[t] <= z["hi"] and VT.h[t] >= z["lo"]]
            if touche:
                self._emettre(self._alerte_s1(s, T, t, tau, ctx, [{"nom": "Prix dans la zone", "zones": touche, "dessin": {}}],
                                              "prepa", notes=self._notes_s1(s, t, tau, ctx)))

    def _notes_s1(self, s, t, tau, ctx):
        cfg, notes = self.cfg, []
        for T2 in ("H1", "H2"):
            V = self.vues[(s, T2)]
            t2 = self.idx(T2, tau)
            E, e, _ = ctx[0]
            VE = self.vues[(s, E)]
            jf = VE.st["jambe_fin"][e]
            if jf >= 0 and V.motif_descendant(t2, int(np.searchsorted(V.deb, VE.deb[jf]))) is not None:
                notes.append(f"Drapeau / wedge en formation ({T2})")
                break
        g = cfg["general"]
        for T2 in cfg["strat1"]["tf_declencheurs"]:
            V = self.vues[(s, T2)]
            t2 = self.idx(T2, tau)
            if V.rsi[t2] < g["rsi_bas"]:
                notes.append(f"RSI {T2} {'sous ' + str(g['rsi_bas']) if s > 0 else 'au-dessus de ' + str(g['rsi_haut'])} "
                             f"({V.rsi[t2] if s > 0 else 100 - V.rsi[t2]:.0f})")
        if self.idx_exact("H4", tau) < 0:
            V4, vh = self.vues[(s, "H4")], self.vues[(s, "H1")]
            e4 = self.idx("H4", tau)
            niv = V4.st["sl_niv"][e4]
            k0 = int(np.searchsorted(vh.fin, V4.fin[e4], "right"))
            k1 = int(np.searchsorted(vh.fin, tau, "right"))
            if not np.isnan(niv) and k1 > k0 and vh.l[k0:k1].min() < niv < vh.c[k1 - 1]:
                notes.append("Mèche sous un swing H4, bougie H4 pas encore clôturée" if s > 0 else
                             "Mèche au-dessus d'un swing H4, bougie H4 pas encore clôturée")
        return notes

    def _alerte_s1(self, s, T, t, tau, ctx, trouves, niveau, notes=None):
        VT, s1 = self.vues[(s, T)], self.cfg["strat1"]
        zones = {}
        for d in trouves:
            for z in d["zones"]:
                zones[z["cle"]] = z
        zl = list(zones.values())
        familles = sorted({self.famille(z) for z in zl})
        entree = float(VT.c[t])
        sl = float(min(z["lo"] for z in zl))
        tf_inval = min((z["tf"] for z in zl), key=rang)
        tp1, tp1_t = self._tp1_s1(s, tau, entree)
        Vi = self.vues[(s, tf_inval)]
        risque = max(entree - sl, s1["risque_min_atr"] * float(Vi.atr[self.idx(tf_inval, tau)]))
        rr = (tp1 - entree) / risque if tp1 is not None else None
        E, e, _ = min(ctx, key=lambda x: rang(x[0]))
        VE = self.vues[(s, E)]
        jd, jf = VE.st["jambe_deb"][e], VE.st["jambe_fin"][e]
        tp2 = {}
        if jd >= 0 and jf > jd:
            tp2["Extension 1,272"] = float(VE.l[jd] + 1.272 * (VE.h[jf] - VE.l[jd]))
        if (s, E) in self.prof:
            vah = self.prof[(s, E)]["VAH"][e]
            if not np.isnan(vah[0]) and (vah[0] + vah[1]) / 2 > entree:
                tp2["VAH" if s > 0 else "VAL"] = float((vah[0] + vah[1]) / 2)
        vol = None
        if jd >= 0 and jf > jd and e > jf:
            vol = bool(VE.v[jd:jf + 1].mean() > VE.v[jf + 1:e + 1].mean())
        ev = VE.st["cassure"][e]
        cassure = None
        if ev >= 0:
            x = VE.st["evenements"][ev]
            cassure = {"tf": E, "type": x["type"], "niv": x["niv"], "piv_t": int(VE.deb[x["piv"]]), "t": int(VE.deb[x["t"]])}
        return {"strat": 1, "sens": s, "niveau": niveau, "tf": T, "tau": tau, "t_bougie": int(VT.deb[t]),
                "declencheurs": [{"nom": d["nom"], "dessin": d["dessin"]} for d in trouves],
                "zones": zl, "familles": familles, "grade": "A" if len(familles) >= 2 else "B",
                "entree": entree, "sl": sl, "risque": risque, "tf_inval": tf_inval, "tp1": tp1, "tp1_t": tp1_t, "tp2": tp2, "rr": rr,
                "rr_ok": rr is not None and rr >= s1["filtre_rr"]["seuil"],
                "bande": (sl, max(z["hi"] for z in zl)),
                "contexte": [{"tf": x[0], "close": float(self.vues[(s, x[0])].c[x[1]]), "ema50": float(self.vues[(s, x[0])].ema_l[x[1]])} for x in ctx],
                "tf_etude": E, "volume_sens": vol, "cassure": cassure, "notes": notes or []}

    # ------------------------------------------------------------------ stratégie 2 : retournement
    def _supports_htf(self, s, tau):
        z2, out = self.cfg["strat2"]["zones_htf"], []
        for tf in z2["profil_tf"]:
            e = self.idx(tf, tau)
            lo, hi = self.prof[(s, tf)]["VAL"][e]
            if not np.isnan(lo):
                out.append({"type": "VAL", "tf": tf, "lo": lo, "hi": hi})
        e4 = self.idx("H4", tau)
        if z2["range"] and self.rng["debut"][e4] >= 0:
            lo, hi = self.rng["bas"][e4] if s > 0 else -self.rng["haut"][e4][::-1]
            out.append({"type": "Bas de range", "tf": "H4", "lo": lo, "hi": hi,
                        "range": {"debut_t": int(self.vues[(1, "H4")].deb[self.rng["debut"][e4]]),
                                  "haut": [float(x) for x in self.rng["haut"][e4]], "bas": [float(x) for x in self.rng["bas"][e4]]}})
        if z2["pdh_pdl"]:
            VD = self.vues[(s, "D")]
            eD = self.idx("D", tau)
            out.append({"type": "PDL", "tf": "D", "lo": VD.l[eD], "hi": VD.l[eD], "debut": int(VD.deb[eD])})
        return out

    def _strat2(self, s, T, t, tau):
        cfg, s2 = self.cfg, self.cfg["strat2"]
        dcl = s2["declencheurs"]
        VT = self.vues[(s, T)]
        cle = (s, T)
        V4 = self.vues[(s, "H4")]
        e4 = self.idx("H4", tau)
        # nouveau sweep sur zone HTF ?
        niv = VT.st["sl_niv"][t - 1]
        if not np.isnan(niv) and VT.l[t] < niv < VT.c[t]:
            VD = self.vues[(s, "D")]
            autorise = not (s2["contre_tendance_d1"] and VD.st["tendance"][self.idx("D", tau)] == 1)
            if autorise:
                tol, perc = s2["tol_zone_atr_h4"] * V4.atr[e4], s2["percage_max_atr_h4"] * V4.atr[e4]
                hits = [z for z in self._supports_htf(s, tau)
                        if VT.l[t] <= z["hi"] + tol and VT.c[t] >= z["lo"] - tol and VT.l[t] >= z["lo"] - perc]
                if hits:
                    p = {"s": t, "W": float(VT.l[t]), "zones": hits, "wedge": [],
                         "sweep": {"niv": float(niv), "piv_t": int(VT.deb[VT.st["sl_piv"][t - 1]]), "t": int(VT.deb[t]),
                                   "meche": float(VT.l[t])}}
                    self.attente_s2[cle] = [p]
                    if cfg["pre_alertes"]["sweep_attente"]:
                        self._emettre(self._alerte_s2(s, T, t, tau, p, [{"nom": "Sweep sur zone HTF — en attente du déclencheur",
                                                                         "dessin": {}}], "prepa"))
        garde = []
        for p in self.attente_s2.get(cle, []):
            if VT.c[t] < p["W"] or t > p["s"] + s2["attente_barres"]:
                continue
            trouves = []
            if dcl["choch"] and t > p["s"]:
                nh = VT.st["sh_niv"][t - 1]
                if not np.isnan(nh) and VT.c[t] > nh:
                    trouves.append({"nom": "CHoCH", "dessin": {"niv": float(nh), "piv_t": int(VT.deb[VT.st["sh_piv"][t - 1]]),
                                                               "t": int(VT.deb[t])}})
            for cle_d, dico, nom_d in (("divergence", VT.div, "Divergence RSI"), ("divergence_cachee", VT.div_cachee, "Divergence RSI cachée")):
                if dcl[cle_d] and t in dico and dico[t][1] >= p["s"] - 2:
                    i1, i2 = dico[t]
                    trouves.append({"nom": nom_d, "dessin": {
                        "p1": {"t": int(VT.deb[i1]), "p": float(VT.l[i1]), "rsi": float(VT.rsi[i1])},
                        "p2": {"t": int(VT.deb[i2]), "p": float(VT.l[i2]), "rsi": float(VT.rsi[i2])}}})
            if dcl["wedge"]:
                tol = cfg["drapeau"]["retest_tol_atr"] * VT.atr[t]
                reste = []
                for w in p["wedge"]:
                    lv = VT.droite(w["motif"], t)
                    if t > w["t"] + cfg["drapeau"]["retest_barres"]:
                        continue
                    if VT.l[t] <= lv + tol:
                        if VT.c[t] > lv:
                            trouves.append({"nom": "Cassure du wedge (retest)", "dessin": dict(w["dessin"], retest_t=int(VT.deb[t]))})
                        continue
                    reste.append(w)
                p["wedge"] = reste
                m = VT.motif_descendant(t, max(p["s"] - cfg["drapeau"]["wedge_fenetre"], 0))
                if m is not None and VT.c[t] > VT.droite(m, t) and VT.c[t - 1] <= VT.droite(m, t - 1):
                    dessin = {"a": {"t": int(VT.deb[m[0]]), "p": m[1]}, "b": {"t": int(VT.deb[m[3]]), "p": float(VT.h[m[3]])},
                              "cassure": {"t": int(VT.deb[t]), "p": float(VT.droite(m, t))}}
                    if cfg["drapeau"]["alerte"] == "cassure":
                        trouves.append({"nom": "Cassure du wedge", "dessin": dessin})
                    else:
                        p["wedge"].append({"t": t, "motif": m, "dessin": dessin})
                        if cfg["pre_alertes"]["cassure_attente_retest"]:
                            self._emettre(self._alerte_s2(s, T, t, tau, p, [{"nom": "Cassure du wedge — en attente du retest",
                                                                             "dessin": dessin}], "prepa"))
            if trouves:
                self._emettre(self._alerte_s2(s, T, t, tau, p, trouves, "setup"))
                continue
            garde.append(p)
        self.attente_s2[cle] = garde

    def _alerte_s2(self, s, T, t, tau, p, trouves, niveau):
        VT, s2 = self.vues[(s, T)], self.cfg["strat2"]
        ref = max((z["tf"] for z in p["zones"] if z["type"] == "VAL"), key=rang, default="H4")
        e = self.idx(ref, tau)
        P = self.prof[(s, ref)]
        poc, vah = P["POC"][e], P["VAH"][e]
        entree, sl = float(VT.c[t]), p["W"]
        tp1 = float((poc[0] + poc[1]) / 2) if not np.isnan(poc[0]) else None
        risque = max(entree - sl, 1e-9)
        rr = (tp1 - entree) / risque if tp1 is not None else None
        types = {(z["type"], z["tf"]) for z in p["zones"]}
        VD = self.vues[(s, "D")]
        eD = self.idx("D", tau)
        return {"strat": 2, "sens": s, "niveau": niveau, "tf": T, "tau": tau, "t_bougie": int(VT.deb[t]),
                "declencheurs": [{"nom": d["nom"], "dessin": d["dessin"]} for d in trouves],
                "zones": p["zones"], "familles": sorted({z["type"] for z in p["zones"]}),
                "grade": "A" if (s2["grade_a_superposition"] and len(types) >= 2) else "B",
                "entree": entree, "sl": sl, "risque": risque, "tf_inval": T, "tp1": tp1, "tp1_t": None,
                "tp2": {"VAH" if s > 0 else "VAL": float((vah[0] + vah[1]) / 2)} if not np.isnan(vah[0]) else {},
                "rr": rr, "rr_ok": rr is not None and rr >= s2["filtre_rr"]["seuil"],
                "bande": (sl, max(max(z["hi"] for z in p["zones"]), entree)),
                "contexte": [{"tf": "D", "tendance": int(VD.st["tendance"][eD])}], "tf_etude": ref, "volume_sens": None,
                "sweep": p["sweep"], "cassure": None, "notes": []}

    # ------------------------------------------------------------------ export (prix d'origine)
    def exporter(self, al, avec_profil=True):
        s = al["sens"]
        P = lambda x: None if x is None else round(float(s * x), 2)  # noqa: E731
        sec = lambda ns: None if ns is None else int(ns // NS)  # noqa: E731

        def pt(d):
            return {"t": sec(d["t"]), "p": P(d["p"]), **({"rsi": round(d["rsi"] if s > 0 else 100 - d["rsi"], 1)} if "rsi" in d else {})}

        zones = []
        for z in al["zones"]:
            lo, hi = bande_origine(z["lo"], z["hi"], s)
            zz = {"type": nom_origine(z["type"], s), "tf": z["tf"], "lo": round(lo, 2), "hi": round(hi, 2), "debut": sec(z.get("debut")),
                  "fin": sec(z.get("fin"))}
            if "fibo" in z:
                f = z["fibo"]
                zz["fibo"] = {"debut": {"t": sec(f["debut_t"]), "p": P(f["debut_p"])}, "fin": {"t": sec(f["fin_t"]), "p": P(f["fin_p"])}}
                zz["niveau"] = z["niveau"]
            if "range" in z:
                zz["range"] = {"debut": sec(z["range"]["debut_t"]), "haut": [round(x, 2) for x in z["range"]["haut"]],
                               "bas": [round(x, 2) for x in z["range"]["bas"]]}
            zones.append(zz)
        dcl = []
        for d in al["declencheurs"]:
            x = {"nom": d["nom"]}
            for k, v in d["dessin"].items():
                if isinstance(v, dict) and "t" in v and "p" in v:
                    x[k] = pt(v)
                elif k == "liquidite":
                    x[k] = {"niv": P(v["niv"]), "piv_t": sec(v["piv_t"])}
                elif k in ("niv",):
                    x[k] = P(v)
                elif k in ("piv_t", "t", "retest_t"):
                    x[k] = sec(v)
                else:
                    x[k] = v
            dcl.append(x)
        out = {
            "id": f"S{al['strat']}-{'L' if s > 0 else 'S'}-{al['tf']}-{sec(al['tau'])}",
            "strategie": al["strat"], "sens": "long" if s > 0 else "short", "niveau": al["niveau"], "tf": al["tf"],
            "heure": sec(al["tau"]), "bougie": sec(al["t_bougie"]), "declencheurs": dcl, "zones": zones,
            "familles": [nom_origine(f, s) for f in al["familles"]], "grade": al["grade"],
            "entree": P(al["entree"]), "tf_etude": al["tf_etude"], "volume_sens": al["volume_sens"], "notes": al["notes"],
            "niveaux_auto": bool(self.cfg["niveaux"]["auto"]), "filtree_rr": al.get("filtree_rr", False),
        }
        if al["niveau"] == "prepa":
            out["statut"] = al.get("statut")
        if self.cfg["niveaux"]["auto"]:   # architecture conservée : niveaux calculés seulement si l'option est activée
            out.update({"invalidation": P(al["sl"]), "tf_invalidation": al["tf_inval"], "risque": round(float(al["risque"]), 2),
                        "tp1": P(al["tp1"]), "tp1_t": sec(al.get("tp1_t")),
                        "tp2": {nom_origine(k, s): P(v) for k, v in al["tp2"].items()},
                        "rr": None if al["rr"] is None else round(al["rr"], 2), "rr_ok": al["rr_ok"], "statut": al.get("statut"),
                        "r": None if al.get("r") is None or np.isnan(al["r"]) else round(al["r"], 2), "clos": sec(al.get("clos"))})
        if al["strat"] == 1:
            out["contexte"] = [{"tf": c["tf"], "close": P(c["close"]), "ema50": P(c["ema50"])} for c in al["contexte"]]
            if al["cassure"]:
                cz = al["cassure"]
                out["cassure"] = {"tf": cz["tf"], "type": cz["type"], "niv": P(cz["niv"]), "piv_t": sec(cz["piv_t"]), "t": sec(cz["t"])}
        else:
            out["tendance_d1"] = "haussière" if al["contexte"][0]["tendance"] * s > 0 else "baissière"
            sw = al["sweep"]
            out["sweep"] = {"niv": P(sw["niv"]), "piv_t": sec(sw["piv_t"]), "t": sec(sw["t"]), "meche": P(sw["meche"])}
        if avec_profil:
            p = self.cfg["profil"]
            tf = al["tf_etude"]
            e = self.idx(tf, al["tau"])
            if p.get("source", "barres") == "barres":
                out["profil"] = dict(instantane_barres(self.df[tf], e, p["jours"][tf], p["niveaux"], p["value_area"]), tf=tf)
            else:
                out["profil"] = dict(instantane(self.h1, self.vues[(1, tf)].fin[e], p["jours"][tf], p["niveaux"], p["value_area"]), tf=tf)
        return out
