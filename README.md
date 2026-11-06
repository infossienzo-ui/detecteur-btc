# Détecteur BTC

Détecteur des deux setups du plan de trading d'Enzo (continuation et retournement) sur BTCUSDT perp.
Il ne prend aucun trade : il prévient sur Telegram et montre sur le dashboard où il a vu le setup.

- **Dashboard** : https://infossienzo-ui.github.io/detecteur-btc/ — graphique en direct : la page lit elle-même les
  bougies Binance perp et suit leur flux temps réel (tous les timeframes, de 1m à D) ; elle recharge les alertes dès
  qu'une vérification en a trouvé de nouvelles.
- **Vérification** : toutes les heures, 2 minutes après l'heure pleine (GitHub Actions, onglet *Actions*).
- **Alertes** : 🟢 setup détecté (un déclencheur clôturé), 🟡 en préparation (contexte bon, rien de clôturé).

## Mise en route

1. Secrets du dépôt (Settings → Secrets and variables → Actions) :
   - `TELEGRAM_TOKEN` : le token donné par @BotFather ;
   - `TELEGRAM_CHAT_ID` : ton identifiant Telegram (donné par @userinfobot) ;
   - `COINALYZE_API_KEY` : ta clé Coinalyze.
2. Settings → Pages → Source : **GitHub Actions**.
3. Onglet Actions → *Détecteur BTC* → **Run workflow** pour la première vérification.
   Telegram reçoit « Détecteur BTC en ligne » quand tout est branché.

## Contenu

| Dossier | Rôle |
|---|---|
| `detecteur/` | Le moteur : structure, zones, profil de volume, les deux stratégies, sans information future. |
| `scripts/maj.py` | La tâche horaire : nouvelles bougies, détection, Telegram, données du dashboard. |
| `config.json` | Tous les paramètres. La page *Paramètres* du dashboard l'écrit pour toi. |
| `data/` | Bougies 1h : historique 2020 → 27/10/2026, puis un fichier CSV par mois ajouté à chaque vérification. |
| `etat/` | Dernière vérification, alertes déjà envoyées, tes niveaux (invalidation, TP) placés depuis le dashboard. |
| `site/` | Le dashboard, publié sur GitHub Pages. |
| `tests/` | Test anti-anticipation : les alertes calculées sur un historique coupé sont identiques. |

## Sources des bougies

Détection : Coinalyze (bougies du perp Binance, clé requise), sinon l'API Binance perp, sinon Binance spot. Les serveurs
de GitHub sont aux États-Unis, où l'API Binance est bloquée : Coinalyze est la source principale.

Graphique du dashboard : bougies du détecteur pour l'historique, puis Binance perp lu par ton navigateur (REST pour les
dernières bougies, WebSocket `/market` pour le temps réel). Si le flux est bloqué, la page relève les bougies toutes les
10 s ; si Binance perp ne répond pas, elle prend Binance spot et l'indique ; sans Binance, elle montre les bougies de la
dernière vérification.
