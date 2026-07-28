# Forex Paper Bots — 3 profils de risque

Trois bots de paper trading forex (compte demo OANDA uniquement, aucun argent réel) tournant automatiquement toutes les 15 minutes via GitHub Actions.

Inspirés des approches open source [EA31337-Libre](https://github.com/EA31337/EA31337-Libre) (filtre de tendance sur moyennes mobiles longues) et [ForexSmartBot](https://github.com/VoxHash/ForexSmartBot) (gestion du risque en % par trade), avec des garde-fous supplémentaires (plafond de marge, coupe-circuit de perte journalière).

| Bot | Paires | Risque/trade | Stop/Take (pips) | Compte OANDA |
|---|---|---|---|---|
| Risque Faible | EUR/USD | 0,5% | 30 / 90 (1:3) | Bot-RisqueFaible |
| Risque Modéré | EUR/USD, GBP/USD, USD/JPY | 2% | 25 / 50 (1:2) | Bot-RisqueModere |
| Risque Élevé | EUR/USD, GBP/USD, USD/JPY, GBP/JPY, AUD/USD, EUR/JPY | 5% | 15 / 30 (1:2) | Bot-RisqueEleve |

Tous les 3 utilisent un croisement de moyennes mobiles (période courte vs longue selon le profil) — pas de martingale, pas de grille : chaque trade a un stop loss fixe et indépendant.

Suivi : onglet [Actions](../../actions) pour les logs, plateforme OANDA (trade.oanda.com) pour le P&L en temps réel par compte.

Aucun gain n'est garanti — outil pédagogique uniquement.
