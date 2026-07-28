# Forex Paper Bots — 3 profils de risque

Trois bots de paper trading forex + matières premières (compte demo OANDA uniquement, aucun argent réel) tournant automatiquement toutes les 5 minutes via GitHub Actions.

Inspirés des approches open source [EA31337-Libre](https://github.com/EA31337/EA31337-Libre) (filtre de tendance sur moyennes mobiles longues) et [ForexSmartBot](https://github.com/VoxHash/ForexSmartBot) (gestion du risque en % par trade), avec des garde-fous supplémentaires (plafond de marge, coupe-circuit de perte journalière).

| Bot | Instruments | Risque/trade | Compte OANDA |
|---|---|---|---|
| Risque Faible | EUR/USD, Cuivre | 0,5% | Bot-RisqueFaible |
| Risque Modéré | EUR/USD, GBP/USD, USD/JPY, Cuivre, Gaz naturel | 2% | Bot-RisqueModere |
| Risque Élevé | EUR/USD, GBP/USD, USD/JPY, GBP/JPY, AUD/USD, EUR/JPY, Cuivre, Gaz naturel | 5% | Bot-RisqueEleve |

Tous les 3 utilisent un croisement de moyennes mobiles sur bougies M5 (période courte vs longue, propre à chaque instrument) — pas de martingale, pas de grille : chaque trade a un stop loss fixe et indépendant.

Paramètres (périodes SMA en nombre de bougies M5, stop/take en pips propres à chaque instrument) et matières premières retenues déterminés par backtest sur ~69 jours de données réelles OANDA (voir commentaires dans `forex_bot.py`). Or et pétrole (WTI/Brent) ont été testés mais écartés : trop peu de combinaisons gagnantes sur la période testée.

Suivi : onglet [Actions](../../actions) pour les logs, plateforme OANDA (trade.oanda.com) pour le P&L en temps réel par compte.

Aucun gain n'est garanti — outil pédagogique uniquement. Les paramètres sont issus d'un backtest sur une seule fenêtre de marché et devront être revalidés périodiquement.
