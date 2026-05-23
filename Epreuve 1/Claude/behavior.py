"""
Analyse comportementale des adversaires + stratégie copycat adaptative.

Fondements théoriques appliqués:
─────────────────────────────────────────────────────────────────────
1. WSLS (Win-Stay Lose-Shift / Pavlov) — Nowak & May 1993, Nature
   "Si notre revenu augmente → garder la position. Si ça baisse → bouger."
   Implémenté dans: harvester_wsls_decision()

2. Generous Tit-for-Tat (GTFT) — Axelrod 1984 + extensions
   "Copier les succès ennemis, pardonner 30% des provocations."
   On imite les positions rentables adverses sans escalade systématique.
   Implémenté dans: copycat_target()

3. Détection comportementale (Adaptive Opponent Policy Detection)
   Classifier chaque ennemi: RUSHER / CAMPER / SABOTEUR / EXPANDER
   Ajuster la réponse selon le type détecté.
   Implémenté dans: classify_enemy()

4. Bounded rationality (température de Boltzmann)
   Les ennemis ne jouent pas parfaitement → exploiter leurs erreurs.
   Implémenté dans: exploitability_score()
─────────────────────────────────────────────────────────────────────
"""

from collections import deque
from game_state import GameState, get_sector, hex_neighbors, hex_distance, ROWS, COLS
from strategy import harvester_income, marginal_income, density_score_area


# ── Classificateur comportemental ─────────────────────────────────────────

# Types d'adversaire
TYPE_UNKNOWN   = 'UNKNOWN'
TYPE_RUSHER    = 'RUSHER'    # Expansion rapide, beaucoup de secteurs
TYPE_CAMPER    = 'CAMPER'    # Concentré dans 1-2 secteurs, peu mobile
TYPE_SABOTEUR  = 'SABOTEUR'  # Sabotage fréquent, peu de récolteuses
TYPE_EXPANDER  = 'EXPANDER'  # Progresse méthodiquement, équilibré


class EnemyTracker:
    """
    Suivi complet d'un adversaire sur la durée de la partie.
    Maintient un historique glissant pour détecter les tendances.
    """

    WINDOW = 20  # Tours de mémoire glissante

    def __init__(self, player_id: int):
        self.player_id    = player_id
        self.pid_str      = str(player_id)

        # Historiques glissants
        self.position_history  = deque(maxlen=self.WINDOW)  # list de (r,c) sets
        self.sector_history    = deque(maxlen=self.WINDOW)  # dict secteur→count
        self.score_history     = deque(maxlen=self.WINDOW)  # scores bruts
        self.count_history     = deque(maxlen=self.WINDOW)  # nb récolteuses

        # État courant
        self.positions      = set()
        self.sector_counts  = {}
        self.score          = 0
        self.count          = 0

        # Métriques dérivées
        self.mobility       = 0.0   # fraction positions changées / tour
        self.aggression     = 0.0   # 0.0-1.0 : fréquence sabotage estimée
        self.score_velocity = 0.0   # gain score/tour sur fenêtre
        self.income_est     = 0.0   # revenu estimé / tour
        self.behavior_type  = TYPE_UNKNOWN
        self.sectors_covered = 0     # nb secteurs avec ≥1 récolteuse

        # WSLS: dernier résultat pour cet ennemi
        self._last_count    = 0
        self._wsls_shifted  = False  # a-t-il bougé le tour passé?

    def update(self, state: GameState, score: int):
        """Mettre à jour à partir de l'état courant."""
        positions = {(r, c) for r in range(ROWS) for c in range(COLS)
                     if state.elements[r][c] == self.pid_str}
        sector_counts = {}
        for r, c in positions:
            s = get_sector(r, c)
            sector_counts[s] = sector_counts.get(s, 0) + 1

        # Historique
        self.position_history.append(frozenset(positions))
        self.sector_history.append(dict(sector_counts))
        self.score_history.append(score)
        self.count_history.append(len(positions))

        # WSLS: détecter si l'ennemi a changé de comportement
        if self._last_count > 0:
            self._wsls_shifted = (len(positions) != self._last_count)
        self._last_count = len(positions)

        # État courant
        self.positions     = positions
        self.sector_counts = sector_counts
        self.score         = score
        self.count         = len(positions)
        self.sectors_covered = len([s for s, n in sector_counts.items() if n >= 1])

        # Calculer métriques
        self._compute_metrics()
        self._classify()

    def _compute_metrics(self):
        """Dériver les métriques comportementales de l'historique."""
        hist = list(self.position_history)
        if len(hist) >= 2:
            # Mobilité: fraction de positions qui ont changé entre tours successifs
            moves = []
            for i in range(1, len(hist)):
                prev, curr = hist[i-1], hist[i]
                union = prev | curr
                if union:
                    changed = len(prev.symmetric_difference(curr)) / (2 * len(union) + 1e-9)
                    moves.append(changed)
            self.mobility = sum(moves) / len(moves) if moves else 0.0

        sc_hist = list(self.score_history)
        if len(sc_hist) >= 2:
            # Score velocity: gain moyen / tour
            diffs = [sc_hist[i] - sc_hist[i-1] for i in range(1, len(sc_hist))]
            self.score_velocity = sum(diffs) / len(diffs) if diffs else 0.0
            # Revenu estimé = score velocity (gain brut, avant dépenses)
            self.income_est = max(0.0, self.score_velocity)

        cnt_hist = list(self.count_history)
        if len(cnt_hist) >= 5:
            # Agressivité: si le count baisse brusquement → probablement sabotage reçu
            # ou si l'ennemi dépense beaucoup (score baisse) sans perte de récolt.
            expansions = sum(1 for i in range(1, len(cnt_hist)) if cnt_hist[i] > cnt_hist[i-1])
            self.aggression = 1.0 - (expansions / (len(cnt_hist) - 1))

    def _classify(self):
        """Classifier le type de comportement."""
        if self.count == 0:
            self.behavior_type = TYPE_UNKNOWN
            return

        if self.sectors_covered >= 3 and self.mobility > 0.15:
            self.behavior_type = TYPE_RUSHER
        elif self.sectors_covered <= 1 and self.count >= 4:
            self.behavior_type = TYPE_CAMPER
        elif self.aggression > 0.6 and self.count <= 3:
            self.behavior_type = TYPE_SABOTEUR
        else:
            self.behavior_type = TYPE_EXPANDER

    @property
    def dominant_sector(self) -> int:
        if not self.sector_counts:
            return -1
        return max(self.sector_counts, key=self.sector_counts.get)

    def density_center(self) -> tuple:
        if not self.positions:
            return (ROWS // 2, COLS // 2)
        avg_r = sum(r for r, c in self.positions) / len(self.positions)
        avg_c = sum(c for r, c in self.positions) / len(self.positions)
        return (int(avg_r), int(avg_c))

    def richest_position(self, state: GameState):
        """Position ennemie avec le meilleur revenu estimé (cible copycat)."""
        if not self.positions:
            return None
        return max(self.positions, key=lambda pos: harvester_income(state, pos[0], pos[1]))

    def exploitability_score(self) -> float:
        """
        Score d'exploitabilité (bounded rationality).
        Un ennemi CAMPER avec faible mobilité est vulnérable au blocage.
        Un ennemi RUSHER dilue ses propres récolteuses → shadow facile.
        """
        if self.behavior_type == TYPE_CAMPER:
            return 0.9  # Très exploitable: on peut le bloquer et voler sa production
        if self.behavior_type == TYPE_RUSHER:
            return 0.7  # Exploitable: dilution → shadow rentable
        if self.behavior_type == TYPE_SABOTEUR:
            return 0.3  # Peu exploitable: éviter, il perd de l'argent
        return 0.5


# ── Stratégie Copycat (GTFT appliqué) ─────────────────────────────────────

def copycat_target(state: GameState, trackers: dict) -> list:
    """
    Generous Tit-for-Tat adapté à la récolte d'épice:
    "Copier la meilleure position ennemie si elle est plus rentable que
    la meilleure position libre actuelle."

    Retourne une liste de cases cibles à imiter (triées par intérêt décroissant),
    en tenant compte du type comportemental de l'ennemi.
    """
    targets = []
    pid_str = str(state.player_id)

    for eid, tracker in trackers.items():
        if tracker.count == 0:
            continue

        exploit = tracker.exploitability_score()

        for er, ec in tracker.positions:
            # Case adjacente libre à l'ennemi (on se pose à côté, pas dessus)
            free_neighbors = [(nr, nc) for nr, nc in hex_neighbors(er, ec)
                              if state.is_free(nr, nc)]
            if not free_neighbors:
                continue

            # Revenu estimé à chaque voisin libre (shadow)
            enemy_inc = harvester_income(state, er, ec)
            # On ne copie que si la zone est rentable
            if enemy_inc < 30:
                continue

            # Voisin libre avec meilleur marginal
            best_neighbor = max(
                free_neighbors,
                key=lambda pos: marginal_income(state, pos[0], pos[1])
            )
            nr, nc = best_neighbor
            mi = marginal_income(state, nr, nc)
            if mi <= 0:
                continue

            # Score copycat: revenu marginal × exploitabilité × densité locale
            local_dens = density_score_area(state, nr, nc, radius=2)
            copycat_score = mi * exploit * (1 + local_dens / 40.0)

            targets.append({
                'r': nr, 'c': nc,
                'score': copycat_score,
                'enemy_id': eid,
                'enemy_pos': (er, ec),
                'enemy_type': tracker.behavior_type,
                'exploit': exploit,
            })

    targets.sort(key=lambda x: x['score'], reverse=True)
    return targets


# ── WSLS pour nos récolteuses ──────────────────────────────────────────────

def harvester_wsls_decision(state: GameState, r: int, c: int,
                             prev_income: float,
                             density_peaks: list) -> tuple:
    """
    Win-Stay Lose-Shift appliqué à chaque récolteuse.
    - Win (revenu ≥ revenu précédent × 0.9) → Stay
    - Lose (revenu < seuil) → Shift vers le meilleur pic de densité

    Retourne (should_move: bool, target: tuple|None, reason: str)
    """
    current_income = harvester_income(state, r, c)

    # Win: revenu stable ou en hausse → rester
    if prev_income > 0 and current_income >= prev_income * 0.9:
        return (False, None, 'WIN_STAY')

    # Lose: chercher le meilleur pic libre
    best_peak = None
    best_score = current_income * 1.15  # seuil minimal de gain pour bouger

    for pr, pc, peak_dens in density_peaks:
        if not state.is_free(pr, pc):
            continue
        sector = get_sector(pr, pc)
        if state.is_danger(sector):
            continue
        mi = marginal_income(state, pr, pc)
        if mi > best_score:
            best_score = mi
            best_peak = (pr, pc)

    if best_peak:
        return (True, best_peak, 'LOSE_SHIFT')
    return (False, None, 'LOSE_NO_TARGET')


# ── Réponse selon le type ennemi ───────────────────────────────────────────

def counter_strategy(tracker: EnemyTracker, state: GameState,
                     my_budget: int) -> dict:
    """
    Retourne les paramètres stratégiques adaptés au type ennemi.

    RUSHER   → on laisse diluer (il se nuit seul), on se place entre ses clusters
    CAMPER   → on le bloque (usine adjacente, shadow intensif)
    SABOTEUR → on l'ignore côté placement, on contre-saboter si budget
    EXPANDER → compétition directe, on se place en avance sur ses routes
    """
    t = tracker.behavior_type
    ec_r, ec_c = tracker.density_center()

    if t == TYPE_RUSHER:
        return {
            'shadow_multiplier':  1.6,   # Shadow rentable: il dilue lui-même
            'block_multiplier':   0.8,   # Peu utile de bloquer (il est partout)
            'sabotage_priority':  0.4,   # Saboter peu (il s'affaiblit seul)
            'intercept_routes':   True,  # Se placer entre ses clusters
            'avoid_direct':       False,
        }
    elif t == TYPE_CAMPER:
        return {
            'shadow_multiplier':  1.2,
            'block_multiplier':   2.0,   # Bloquer fort: il est vulnérable fixe
            'sabotage_priority':  0.8,   # Saboter: il est concentré
            'intercept_routes':   False,
            'avoid_direct':       False,
        }
    elif t == TYPE_SABOTEUR:
        return {
            'shadow_multiplier':  0.5,   # Éviter ses zones (risque sabotage)
            'block_multiplier':   0.3,
            'sabotage_priority':  1.0,   # Contre-saboter en priorité
            'intercept_routes':   False,
            'avoid_direct':       True,  # Rester loin de lui
        }
    else:  # EXPANDER / UNKNOWN
        return {
            'shadow_multiplier':  1.0,
            'block_multiplier':   1.0,
            'sabotage_priority':  0.5,
            'intercept_routes':   True,  # Anticiper sa progression
            'avoid_direct':       False,
        }


# ── Score de menace global ─────────────────────────────────────────────────

def threat_score(trackers: dict, my_score: int) -> float:
    """
    Score de menace global 0-1.
    0 = personne ne nous menace, 1 = on est clairement dernier.
    Basé sur l'écart de score velocity et le positionnement relatif.
    """
    if not trackers:
        return 0.0

    # Score velocity max ennemi vs le nôtre
    max_enemy_vel = max(t.score_velocity for t in trackers.values())
    # On n'a pas accès à notre propre velocity ici, approximation par comparaison
    best_enemy_score = max((t.score for t in trackers.values()), default=0)
    if best_enemy_score <= 0:
        return 0.0

    relative = (best_enemy_score - my_score) / (best_enemy_score + my_score + 1)
    velocity_gap = min(1.0, max(0.0, max_enemy_vel / 200.0))
    return min(1.0, 0.6 * max(0.0, relative) + 0.4 * velocity_gap)
