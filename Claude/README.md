# For The Spice — IA Elite

## Lancement

```bash
python3 main.py [NOM_EQUIPE]
```

Nécessite Python 3.7+. Aucune dépendance externe.

---

## Architecture

| Fichier | Rôle |
|---|---|
| `main.py` | Réseau TCP non-bloquant (`select`), buffer, handshake |
| `game_state.py` | Modèle grille hexagonale, distance cubique exacte, cache |
| `strategy.py` | Calculs revenus, heatmap, ROI, sabotage, repositionnement |
| `brain.py` | Cerveau stratégique, phases, décisions par tour |

---

## Stratégie détaillée

### Phases

| Phase | Tours | Cible récolteuses | Usines max | Sabotage |
|---|---|---|---|---|
| EARLY | 1–40 | 5 | 1 | Non |
| MID | 41–130 | 8 | 3 | Oui si ≥2 ennemis |
| LATE | 131–200 | On garde l'existant | 3 | Harcèlement (≥1 ennemi) |

### Ordre de priorité par tour (sur 15 commandes max)

1. **Info** (4 cmds): ELEMENTS, DENSITE (tous les 20 tours), WARNING, SCORES
2. **Survie**: évacuation immédiate si WARNING=DANGER, vers la meilleure case safe
3. **Vision**: ornithoptères dans chaque secteur actif, renouvelés toutes les 4 tours
4. **Expansion**: achat sur les cases heatmap, ROI vérifié
5. **Industrie**: usine si ROI positif sur les tours restants
6. **Optimisation**: repositionnement si +35% de revenu potentiel
7. **Sabotage**: frappe les secteurs sans nos unités + cooldown 3 tours
8. **FINDETOUR**

---

## Points clés vs bots naïfs

### Distance hexagonale exacte
Utilise les coordonnées cubiques (`to_cube`) au lieu de Manhattan.
Évite les erreurs tactiques sur les bords et diagonales.

### Valeur marginale avec dilution
`marginal_income(r,c)` calcule:
- Notre gain sur chaque case de la zone
- **Moins** la perte infligée à nos récolteuses voisines (partage dilué)

Ce calcul évite de placer des récolteuses qui se cannibalisent mutuellement.

### Heatmap multi-facteurs
Score final = valeur marginale
- × 1.5 si proche d'une usine active (boost garanti)
- × 1.2 si blocus industriel ennemi (case rentable + nuisance)
- × 0.5–0.8 si anti-clustering (secteur déjà saturé)
- − pénalité voisins ennemis directs

### ROI dynamique des usines
`factory_roi = gain_par_tour × tours_restants − 5000`
Ne place une usine que si le ROI est positif (ou si turn < 15).

### Sabotage intelligent
Valeur sabotage = `ennemis_détruits × 3000 − 600`
Jamais saboter un secteur où on est présent.
En LATE: harcèlement pur (même 1 ennemi suffit).

### Budget local
Le brain maintient `self.budget` localement mis à jour à chaque achat/sabotage,
sans re-requêter SCORES (économise des commandes).

---

## Situations de match couvertes

| Situation | Réponse |
|---|---|
| Attaque de ver prévue | Évacuation complète du secteur avant la fin du tour |
| Secteur saturé d'alliés | Pénalité heatmap → expansion vers autres secteurs |
| Usine ennemie proche | Bonus heatmap × 1.2 → on se place dessus pour en profiter |
| Adversaire très riche | Sabotage préventif en MID/LATE |
| Phase finale (>170 tours) | Arrêt des achats, repositionnements conservateurs |
| Récolteuse sur case vide (densité 0) | Repositionnement forcé immédiat |
| Concurrent sur même zone | `marginal_income` réduit automatiquement → on va ailleurs |
