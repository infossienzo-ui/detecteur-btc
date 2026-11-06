"""Aucune information future : les alertes détectées avant T sont identiques que l'historique s'arrête à T ou continue.
(Le suivi — TP1 / invalidation — dépend évidemment de la suite : il n'est pas comparé.)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from detecteur import config, donnees
from detecteur.moteur import Moteur

CHAMPS = ("id", "niveau", "declencheurs", "zones", "familles", "grade", "entree", "invalidation", "tp1", "tp2", "rr",
          "notes", "contexte", "cassure", "sweep", "tf_etude", "volume_sens")


def signature(M, al):
    x = M.exporter(al, avec_profil=False)
    # « fin » d'une zone (bougie qui l'a comblée / cassée) sert seulement au dessin, après coup : hors comparaison
    x["zones"] = [{k: v for k, v in z.items() if k != "fin"} for z in x["zones"]]
    return {k: x.get(k) for k in CHAMPS}


cfg = config.charger()
h1 = donnees.charger_h1(os.path.join(os.path.dirname(__file__), "..", "data", "klines_perp_1h_base.parquet"))
D0 = pd.Timestamp("2025-06-01").value
M = Moteur(h1, cfg, log=lambda *a: None)
ref = M.executer(debut=D0)
erreurs = 0
for coupe in ("2025-09-17 13:00", "2026-03-02 07:00", "2026-08-21 22:00"):
    T = pd.Timestamp(coupe)
    Mc = Moteur(h1[h1.index < T], cfg, log=lambda *a: None)
    cut = Mc.executer(debut=D0)
    a = [signature(M, x) for x in ref if x["tau"] <= T.value]
    b = [signature(Mc, x) for x in cut if x["tau"] <= T.value]
    if a != b:
        erreurs += 1
        for i, (u, v) in enumerate(zip(a, b)):
            if u != v:
                print(f"✗ coupe {coupe} : première différence à l'alerte {i} ({u['id']} / {v['id']})")
                for k in CHAMPS:
                    if u.get(k) != v.get(k):
                        print("   ", k, u.get(k), "≠", v.get(k))
                break
        else:
            print(f"✗ coupe {coupe} : {len(a)} alertes contre {len(b)}")
    else:
        print(f"✅ coupe {coupe} : {len(a)} alertes identiques")
print("OK : aucune anticipation" if erreurs == 0 else f"ÉCHEC : {erreurs} coupe(s)")
