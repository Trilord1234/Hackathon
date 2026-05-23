# Commandes — For The Spice

## Actions (modifient l'état du jeu)

| Commande                                     | Arguments   | Effet                                     |
| -------------------------------------------- | ----------- | ----------------------------------------- |
| `AJOUTERRECOLTEUSE\|ligne\|colonne`          | 0-15 / 0-17 | Place une récolteuse (coûte 3000)         |
| `AJOUTERUSINE\|ligne\|colonne`               | 0-15 / 0-17 | Place une usine (coûte 5000)              |
| `DEPLACER\|ligne\|col\|ligne_dest\|col_dest` | 0-15 / 0-17 | Déplace une récolteuse (gratuit)          |
| `AJOUTERORNI\|secteur`                       | 0-3         | Déploie un ornithoptère pour 5 tours et coute 400  |
| `SABOTER\|secteur`                           | 0-3         | Attire un ver sur le secteur (coûte 600) |
| `FINDETOUR`                                  | aucun       | Termine votre tour                        |

---

## Demandes (informations uniquement)

| Commande   | Réponse                                                                         |
| ---------- | ------------------------------------------------------------------------------- |
| `DENSITE`  | Chaîne 288 caractères (16×18), chiffres `1`–`4`                                 |
| `ELEMENTS` | Chaîne 288 caractères : `0/1/2/3` = récolteuse joueur, `X` = libre, `U` = usine |
| `WARNING`  | `INCONNU` / `CALME` / `DANGER` pour chacun des 4 secteurs                       |
| `SCORES`   | Score de chaque joueur séparé par `\|`                                          |

---

## Rappels importants

- **15 commandes + demandes maximum** par tour
- **5 secondes maximum** pour répondre au serveur
- Le séparateur est toujours `|`
- Les demandes consomment votre quota de 15
