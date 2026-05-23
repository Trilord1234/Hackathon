# Commandes — For The Spice

## Actions (modifient l'état du jeu)

| Commande                                     | Arguments   | Prix    | Effet en jeu                                                                  | Exemple |
| -------------------------------------------- | ----------- | ------- | ----------------------------------------------------------------------------- | ------- |
| `AJOUTERRECOLTEUSE\|ligne\|colonne`          | 0-15 / 0-17 | 3000    | Récolte l'épice sur sa case + les 6 cases adjacentes à chaque tour            | `AJOUTERRECOLTEUSE\|3\|4` |
| `AJOUTERUSINE\|ligne\|colonne`               | 0-15 / 0-17 | 5000    | Double la production des cases dans un rayon de 2. Ne produit pas elle-même. Survit aux vers | `AJOUTERUSINE\|7\|9` |
| `DEPLACER\|ligne\|col\|ligne_dest\|col_dest` | 0-15 / 0-17 | Gratuit | Téléporte une récolteuse n'importe où sur une case libre                      | `DEPLACER\|3\|4\|10\|4` |
| `AJOUTERORNI\|secteur`                       | 0-3         | 400     | Permet de recevoir WARNING sur ce secteur pendant 5 tours                     | `AJOUTERORNI\|0` |
| `SABOTER\|secteur`                           | 0-3         | 500     | Attire un vers qui détruira toutes les récolteuses du secteur au tour suivant  | `SABOTER\|2` |
| `FINDETOUR`                                  | aucun       | Gratuit | Termine votre tour, obligatoire                                                | `FINDETOUR` |

---

## Demandes (informations uniquement)

| Commande   | Réponse                                                                          | Exemple de réponse |
| ---------- | -------------------------------------------------------------------------------- | ------------------ |
| `DENSITE`  | Chaîne 288 caractères (16×18), chiffres `1`–`4`                                  | `"1234312341234..."` |
| `ELEMENTS` | Chaîne 288 caractères : `0/1/2/3` = récolteuse joueur, `X` = libre, `U` = usine  | `"XXX0XUXX1..."` |
| `WARNING`  | `INCONNU` / `CALME` / `DANGER` pour chacun des 4 secteurs                        | `"DANGER\|CALME\|INCONNU\|CALME"` |
| `SCORES`   | Score de chaque joueur séparé par `\|`                                           | `"15000\|8000\|12000\|3000"` |

---

## Rappels importants

- **15 commandes + demandes maximum** par tour
- **5 secondes maximum** pour répondre au serveur
- Le séparateur est toujours `|`
- Les demandes consomment votre quota de 15