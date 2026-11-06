"""Paramètres du détecteur. Tout ce qui est réglable est ici ; la page « Paramètres » du dashboard écrit config.json,
qui remplace ces valeurs par défaut. SCHEMA donne le libellé et l'aide de chaque paramètre (affichés sur la page)."""
import copy
import json
import os

DEFAUT = {
    "general": {
        "symbole": "BTCUSDT",
        "swing_n": 2,
        "emas": [8, 21, 50, 200],
        "ema_declencheurs": [21, 50],
        "ema_lente": 50,
        "rsi_periode": 14,
        "rsi_haut": 70,
        "rsi_bas": 30,
        "atr_periode": 14,
    },
    "niveaux": {"auto": False},
    "profil": {
        "jours": {"M1": 0.2083, "M5": 0.625, "M15": 2, "M30": 3.75, "H1": 8, "H2": 12, "H3": 15, "H4": 18, "H5": 21,
                  "H6": 25, "H8": 28, "H12": 40, "D": 75},
        "source": "barres",
        "value_area": 0.70,
        "niveaux": 20,
    },
    "strat1": {
        "actif": True,
        "tf_contexte": ["H4", "H6", "D"],
        "tf_declencheurs": ["H1", "H2", "H4"],
        "zones": {"OB": True, "FVG": True, "Fibo": True, "Profil": True, "EMA50": True},
        "fibo_niveaux": [0.382, 0.5, 0.618, 0.65, 0.705, 1.0],
        "fibo_golden": [0.618, 0.65],
        "fibo_epaisseur_atr": 0.1,
        "fvg_min_atr": 0.1,
        "fvg_comble": "meches",
        "ema_zone_atr": 0.1,
        "ob_corps": False,
        "ob_recherche": 10,
        "zones_max_par_type": 4,
        "declencheurs": {"reclaim": True, "rejet": True, "drapeau": True, "divergence": True, "divergence_cachee": True,
                         "reprise_ema": True},
        "pinbar_meche": 0.5,
        "reprise_ema_tf_min": "H2",
        "filtre_rr": {"actif": False, "seuil": 1.0},
        "risque_min_atr": 0.5,
    },
    "strat2": {
        "actif": True,
        "tf_declencheurs": ["H1", "H2", "H4"],
        "contre_tendance_d1": True,
        "zones_htf": {"profil_tf": ["H4", "H6", "D"], "range": True, "pdh_pdl": True},
        "tol_zone_atr_h4": 0.25,
        "percage_max_atr_h4": 1.0,
        "range": {"jours_min": 3, "tol_atr_h4": 0.5, "fenetre_jours": 30, "largeur_min_atr_h4": 2.0},
        "declencheurs": {"divergence": True, "divergence_cachee": True, "choch": True, "wedge": True},
        "attente_barres": 24,
        "filtre_rr": {"actif": False, "seuil": 2.0},
        "grade_a_superposition": False,
    },
    "divergence": {"ecart_min": 5, "ecart_max": 60},
    "drapeau": {"alerte": "retest", "retest_barres": 10, "retest_tol_atr": 0.1, "wedge_fenetre": 30},
    "pre_alertes": {"actif": True, "prix_dans_zone": True, "cassure_attente_retest": True, "sweep_attente": True},
    "alertes": {"suivi_jours": 10, "pre_alerte_heures": 48},
    "affichage": {"fvg_max": 50, "rsi_zones": [70, 30]},
}

# (chemin, libellé, type, aide) ; type : bool, int, float, choix:a|b, liste:H1|H2|..., txt
SCHEMA = [
    ("Général", [
        ("general.swing_n", "Swing : bougies de chaque côté", "int", "Un swing high / low dépasse ce nombre de bougies de chaque côté (plan : 2)."),
        ("general.emas", "EMA affichées", "nombres", "Sur le graphique (8, 21, 50, 200)."),
        ("general.ema_declencheurs", "EMA des déclencheurs", "nombres", "Reclaim et reprise de l'EMA (21 et 50)."),
        ("general.ema_lente", "EMA du contexte", "int", "Prix du bon côté de cette EMA, et zone « EMA » (50)."),
        ("general.rsi_periode", "RSI : période", "int", ""),
        ("general.rsi_haut", "RSI : zone haute", "int", ""),
        ("general.rsi_bas", "RSI : zone basse", "int", ""),
        ("general.atr_periode", "ATR : période", "int", "L'ATR sert aux tolérances (épaisseur des zones, distance au niveau)."),
    ]),
    ("Profil de volume (ton outil)", [
        ("profil.jours.M1", "Période 1m (jours)", "float", "Ton outil : 5 heures."),
        ("profil.jours.M5", "Période 5m (jours)", "float", "Ton outil : 15 heures."),
        ("profil.jours.M15", "Période 15m (jours)", "float", "Ton outil : 48 heures."),
        ("profil.jours.M30", "Période 30m (jours)", "float", "Ton outil : 90 heures."),
        ("profil.jours.H1", "Période 1h (jours)", "float", ""),
        ("profil.jours.H2", "Période 2h (jours)", "float", ""),
        ("profil.jours.H3", "Période 3h (jours)", "float", "Absente de ton outil : valeur choisie entre 2h et 4h, à confirmer."),
        ("profil.jours.H4", "Période 4h (jours)", "float", ""),
        ("profil.jours.H5", "Période 5h (jours)", "float", "Absente de ton outil : valeur choisie entre 4h et 6h, à confirmer."),
        ("profil.jours.H6", "Période 6h (jours)", "float", ""),
        ("profil.jours.H8", "Période 8h (jours)", "float", ""),
        ("profil.jours.H12", "Période 12h (jours)", "float", ""),
        ("profil.jours.D", "Période D (jours)", "float", ""),
        ("profil.value_area", "Value area", "float", "Part du volume dans la value area (0,7 = 70 %)."),
        ("profil.niveaux", "Résolution (niveaux)", "int", ""),
    ]),
    ("Stratégie 1 : continuation", [
        ("strat1.actif", "Stratégie active", "bool", ""),
        ("strat1.tf_contexte", "Timeframes de contexte", "liste:H4|H6|D", "Structure + prix du bon côté de l'EMA 50 sur au moins un de ces timeframes."),
        ("strat1.tf_declencheurs", "Timeframes des déclencheurs", "liste:H1|H2|H4", ""),
        ("strat1.zones.OB", "Zone : order block", "bool", ""),
        ("strat1.zones.FVG", "Zone : imbalance (FVG)", "bool", ""),
        ("strat1.zones.Fibo", "Zone : Fibo de la jambe d'impulsion", "bool", ""),
        ("strat1.zones.Profil", "Zone : POC / VAH / VAL", "bool", ""),
        ("strat1.zones.EMA50", "Zone : EMA 50", "bool", ""),
        ("strat1.fibo_niveaux", "Fibo : niveaux", "nombres", "Chaque niveau est une zone à part, sauf la golden zone."),
        ("strat1.fibo_golden", "Fibo : golden zone (bande entre deux niveaux)", "nombres", "0,618 à 0,65."),
        ("strat1.fibo_epaisseur_atr", "Fibo : demi-épaisseur d'un niveau (× ATR)", "float", "Un niveau seul est une zone fine : niveau ± cette valeur × ATR du timeframe de contexte."),
        ("strat1.fvg_min_atr", "FVG : taille minimum (× ATR)", "float", "Ignore les imbalances trop petites."),
        ("strat1.fvg_comble", "FVG : supprimée quand", "choix:meches|cloture", "Mèches : dès qu'une mèche la comble entièrement (full fill)."),
        ("strat1.ema_zone_atr", "Zone EMA 50 : demi-épaisseur (× ATR)", "float", ""),
        ("strat1.ob_corps", "OB : corps seulement (sinon mèches)", "bool", ""),
        ("strat1.zones_max_par_type", "Zones gardées par type", "int", "Nombre d'OB / FVG récents non invalidés gardés par timeframe."),
        ("strat1.declencheurs.reclaim", "Déclencheur : reclaim", "bool", ""),
        ("strat1.declencheurs.rejet", "Déclencheur : bougie de rejet", "bool", ""),
        ("strat1.declencheurs.drapeau", "Déclencheur : cassure du drapeau", "bool", ""),
        ("strat1.declencheurs.divergence", "Déclencheur : divergence RSI classique", "bool", ""),
        ("strat1.declencheurs.divergence_cachee", "Déclencheur : divergence RSI cachée", "bool", ""),
        ("strat1.declencheurs.reprise_ema", "Déclencheur : reprise de l'EMA", "bool", ""),
        ("strat1.pinbar_meche", "Pin bar : mèche minimum", "float", "Part de la bougie (0,5 = 50 %)."),
        ("strat1.reprise_ema_tf_min", "Reprise d'EMA : timeframe minimum", "choix:H1|H2|H4", "Plan : H2 minimum."),
        ("strat1.filtre_rr.actif", "Filtre R:R actif", "bool", "Nécessite l'invalidation et le TP automatiques : reste inactif tant que tu les places toi-même."),
        ("strat1.filtre_rr.seuil", "R:R minimum jusqu'au TP1", "float", ""),
        ("strat1.risque_min_atr", "Distance minimum à l'invalidation (× ATR du TF d'étude)", "float",
         "Pour le calcul du R:R et du suivi : sur une zone très fine, l'entrée peut être à quelques dollars de l'invalidation et le R:R ne veut plus rien dire."),
    ]),
    ("Stratégie 2 : retournement", [
        ("strat2.actif", "Stratégie active", "bool", ""),
        ("strat2.tf_declencheurs", "Timeframes du sweep et des déclencheurs", "liste:H1|H2|H4", ""),
        ("strat2.contre_tendance_d1", "Uniquement contre la tendance D1", "bool", "Coché : D1 haussier → seulement des retournements baissiers, et inversement."),
        ("strat2.zones_htf.profil_tf", "VAH / VAL des profils", "liste:H4|H6|D", ""),
        ("strat2.zones_htf.range", "Extrémités de range H4", "bool", ""),
        ("strat2.zones_htf.pdh_pdl", "Plus haut / plus bas D1 précédent", "bool", ""),
        ("strat2.tol_zone_atr_h4", "Distance max au niveau (× ATR H4)", "float", "« Prix sur zone » : la mèche arrive à moins de cette distance."),
        ("strat2.percage_max_atr_h4", "Perçage max au-delà du niveau (× ATR H4)", "float", ""),
        ("strat2.range.jours_min", "Range : durée minimum (jours)", "int", ""),
        ("strat2.range.tol_atr_h4", "Range : écart max entre sommets / creux (× ATR H4)", "float", ""),
        ("strat2.range.fenetre_jours", "Range : recherche sur (jours)", "int", ""),
        ("strat2.range.largeur_min_atr_h4", "Range : largeur minimum (× ATR H4)", "float", ""),
        ("strat2.declencheurs.divergence", "Déclencheur : divergence RSI classique", "bool", ""),
        ("strat2.declencheurs.divergence_cachee", "Déclencheur : divergence RSI cachée", "bool", ""),
        ("strat2.declencheurs.choch", "Déclencheur : CHoCH clôturé", "bool", ""),
        ("strat2.declencheurs.wedge", "Déclencheur : cassure de wedge", "bool", ""),
        ("strat2.attente_barres", "Attente max du déclencheur après le sweep (bougies)", "int", ""),
        ("strat2.filtre_rr.actif", "Filtre R:R actif", "bool", "Nécessite l'invalidation et le TP automatiques."),
        ("strat2.filtre_rr.seuil", "R:R minimum jusqu'au TP1", "float", ""),
        ("strat2.grade_a_superposition", "Grade A si 2 zones HTF superposées", "bool", "Décoché : toujours grade B (contre-tendance)."),
    ]),
    ("Divergence RSI (règle classique)", [
        ("divergence.ecart_min", "Écart min entre les deux creux / sommets (bougies)", "int", "Valeur de l'indicateur standard de TradingView : 5."),
        ("divergence.ecart_max", "Écart max entre les deux creux / sommets (bougies)", "int", "Valeur de l'indicateur standard de TradingView : 60."),
    ]),
    ("Drapeau / wedge", [
        ("drapeau.alerte", "Alerte 🟢 à la", "choix:retest|cassure", "Retest : la cassure donne une pré-alerte 🟡, le retest donne l'alerte 🟢."),
        ("drapeau.retest_barres", "Attente max du retest (bougies)", "int", ""),
        ("drapeau.retest_tol_atr", "Tolérance du retest (× ATR)", "float", ""),
        ("drapeau.wedge_fenetre", "Wedge du retournement : recherche sur (bougies)", "int", ""),
    ]),
    ("Pré-alertes 🟡", [
        ("pre_alertes.actif", "Pré-alertes actives", "bool", ""),
        ("pre_alertes.prix_dans_zone", "Prix dans la zone (stratégie 1)", "bool", ""),
        ("pre_alertes.cassure_attente_retest", "Cassure faite, en attente du retest", "bool", ""),
        ("pre_alertes.sweep_attente", "Sweep sur zone HTF, en attente du déclencheur (stratégie 2)", "bool", ""),
    ]),
    ("Invalidation et TP", [
        ("niveaux.auto", "Calcul automatique", "bool", "Décoché : tu places toi-même l'invalidation et les TP sur chaque alerte (le code reste en place)."),
    ]),
    ("Affichage", [
        ("affichage.fvg_max", "FVG affichées au maximum", "int", "Comme ton indicateur FVG (50)."),
    ]),
    ("Alertes", [
        ("alertes.suivi_jours", "Une alerte par zone pendant (jours)", "int", "Pas de nouvelle alerte sur la même zone tant qu'elle n'est pas cassée, ou pendant ce délai."),
        ("alertes.pre_alerte_heures", "Durée d'une pré-alerte (heures)", "int", ""),
    ]),
]


def _fusion(base, ajout):
    for k, v in ajout.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _fusion(base[k], v)
        else:
            base[k] = v


def charger(chemin=None):
    cfg = copy.deepcopy(DEFAUT)
    if chemin and os.path.exists(chemin):
        with open(chemin, encoding="utf-8") as f:
            _fusion(cfg, json.load(f))
    return cfg
