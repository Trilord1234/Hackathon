"""
Cerveau Elite - For The Spice
Stratégie adaptative par phase + toutes les optimisations fusionnées.

Ordre de priorité strict par tour:
  0. Collecte d'info (4 cmds)
  1. Survie: évacuer les récolteuses en danger (DANGER warning)
  2. Vision: renouveler ornithoptères dans secteurs actifs
  3. Expansion agressivité: acheter récolteuses (heatmap)
  4. Industrie: placer usines (ROI positif)
  5. Optimisation: repositionner récolteuses peu rentables
  6. Sabotage: frapper les ennemis concentrés
  7. FINDETOUR
"""

import logging
from game_state import (
    GameState, get_sector, hex_neighbors, hex_distance,
    ROWS, COLS, cells_within_radius
)
from strategy import (
    marginal_income, harvester_income, build_heatmap,
    best_factory_position, factory_roi, sabotage_value,
    should_relocate, total_income, _find_best_free
)

log = logging.getLogger(__name__)

COST_HARVESTER = 3000
COST_FACTORY   = 5000
COST_SABOTAGE  = 600
ORNI_REFRESH   = 4   # Renouveler toutes les 4 tours (orni dure 5 tours)

# Cibles de récolteuses selon la phase
TARGETS = {
    'EARLY': 5,   # Tours 1-40
    'MID':   8,   # Tours 41-130
    'LATE':  0,   # Tours 131+: on arrête d'acheter
}
FACTORY_TARGETS = {
    'EARLY': 1,
    'MID':   3,
    'LATE':  3,
}


def get_phase(turn: int) -> str:
    if turn <= 40:  return 'EARLY'
    if turn <= 130: return 'MID'
    return 'LATE'


class Brain:
    def __init__(self, player_id: int, team_name: str, net):
        self.player_id  = player_id
        self.team_name  = team_name
        self.net        = net
        self.state      = GameState(player_id)

        self.orni_deployed  = {}   # secteur -> tour dernier déploiement
        self.sabotaged      = {}   # secteur -> tour dernier sabotage
        self.density_fetched = False

        # Compteur de commandes restantes ce tour
        self.cmds = 0

        # Budget local mis à jour sans re-fetch
        self.budget = 0

    # ── Interface publique ─────────────────────────────────────────────────

    def play_turn(self, turn: int):
        self.state.turn = turn
        self.cmds = 15
        phase = get_phase(turn)
        turns_left = 200 - turn

        # ── 0. COLLECTE D'INFO ────────────────────────────────────────────
        self._fetch_elements()
        if not self.density_fetched or turn % 20 == 1:
            self._fetch_density()
        self._fetch_warnings()
        self._fetch_scores()

        self.budget = self.state.my_score()
        n_harv  = len(self.state.my_harvesters)
        n_fact  = len(self.state.my_factories)
        inc     = total_income(self.state)

        log.info(f"[{phase}] T{turn} | Budget:{self.budget} | H:{n_harv} | "
                 f"F:{n_fact} | Income:{inc:.0f}/tour | Cmds:{self.cmds}")
        log.info(f"Warnings: {self.state.warnings}")

        # Secteurs dangereux
        dangerous = {s for s in range(4) if self.state.is_danger(s)}
        # Pré-identifier les secteurs qu'on va saboter pour les exclure de la heatmap
        condemned = self._preview_sabotage_targets(turn, phase)

        # ── 1. SURVIE ─────────────────────────────────────────────────────
        self._evacuate(dangerous)

        # ── 2. VISION ─────────────────────────────────────────────────────
        self._deploy_ornis(turn)

        # ── 3. EXPANSION ──────────────────────────────────────────────────
        heatmap = build_heatmap(self.state, turn, phase, dangerous, condemned)
        if phase != 'LATE':
            self._buy_harvesters(heatmap, phase, turns_left)

        # ── 4. INDUSTRIE ──────────────────────────────────────────────────
        if phase != 'LATE':
            self._buy_factories(phase, turns_left)

        # ── 5. OPTIMISATION ───────────────────────────────────────────────
        if turn >= 10:
            self._reposition(dangerous)

        # ── 6. SABOTAGE ───────────────────────────────────────────────────
        self._sabotage(turn, phase, condemned)

        # ── 7. FIN DE TOUR ────────────────────────────────────────────────
        self.net.send("FINDETOUR")
        log.info(f"FIN T{turn} | Cmds restantes: {self.cmds}")

    # ── Fetch helpers ──────────────────────────────────────────────────────

    def _fetch_elements(self):
        resp = self.net.request("ELEMENTS")
        self.state.update_elements(resp)
        self.cmds -= 1

    def _fetch_density(self):
        resp = self.net.request("DENSITE")
        self.state.update_density(resp)
        self.density_fetched = True
        self.cmds -= 1

    def _fetch_warnings(self):
        resp = self.net.request("WARNING")
        self.state.update_warnings(resp)
        self.cmds -= 1

    def _fetch_scores(self):
        resp = self.net.request("SCORES")
        self.state.update_scores(resp)
        self.cmds -= 1

    # ── Action helpers ─────────────────────────────────────────────────────

    def _act(self, cmd) -> bool:
        """Envoie une action de jeu si on a des commandes restantes."""
        if self.cmds <= 1:  # garder 1 pour FINDETOUR
            return False
        ok = self.net.send_action(cmd)
        self.cmds -= 1
        return ok

    # ── 1. Survie ──────────────────────────────────────────────────────────

    def _evacuate(self, dangerous: set):
        """Déplace toutes les récolteuses hors des secteurs en DANGER."""
        moved = set()
        for r, c in list(self.state.my_harvesters):
            if self.cmds <= 1:
                break
            sector = get_sector(r, c)
            if sector not in dangerous:
                continue

            # Chercher la meilleure case safe, pas déjà ciblée ce tour
            dest = _find_best_free(
                self.state,
                avoid_sectors=dangerous,
                exclude=moved | {(r, c)}
            )
            if dest is None:
                # Si toutes les cases safe sont prises, prendre n'importe quelle case libre
                for nr in range(ROWS):
                    for nc in range(COLS):
                        if self.state.is_free(nr, nc) and get_sector(nr, nc) not in dangerous:
                            dest = (nr, nc)
                            break
                    if dest:
                        break

            if dest:
                nr, nc = dest
                if self._act(f"DEPLACER|{r}|{c}|{nr}|{nc}"):
                    log.info(f"  [SURVIE] ({r},{c}) → ({nr},{nc})")
                    self.state.move_harvester(r, c, nr, nc)
                    moved.add((nr, nc))

    # ── 2. Ornithoptères ───────────────────────────────────────────────────

    def _deploy_ornis(self, turn: int):
        """Déploie des ornithoptères dans tous les secteurs où on est actif."""
        active_sectors = {get_sector(r, c) for r, c in self.state.my_harvesters}
        for sector in active_sectors:
            if self.cmds <= 1:
                break
            last = self.orni_deployed.get(sector, -999)
            if turn - last >= ORNI_REFRESH:
                if self._act(f"AJOUTERORNI|{sector}"):
                    self.orni_deployed[sector] = turn
                    log.info(f"  [ORNI] Secteur {sector}")

    # ── 3. Achats récolteuses ──────────────────────────────────────────────

    def _buy_harvesters(self, heatmap: list, phase: str, turns_left: int):
        """Achète des récolteuses sur les meilleures cases de la heatmap."""
        target = TARGETS[phase]
        n = len(self.state.my_harvesters)

        # En tout début de partie: achat agressif
        if self.state.turn <= 3:
            target = 4

        occupied_this_turn = set()

        for entry in heatmap:
            if self.cmds <= 1:
                break
            if n >= target:
                break
            if self.budget < COST_HARVESTER:
                break

            r, c = entry['r'], entry['c']
            if (r, c) in occupied_this_turn:
                continue
            if not self.state.is_free(r, c):
                continue

            # Vérif ROI minimal (sauf début de partie)
            score = entry['score']
            if turns_left > 0 and score * turns_left < COST_HARVESTER and self.state.turn > 10:
                break  # Plus rentable d'acheter

            # Pas trop proche d'un ennemi direct (anti-partage)
            enemy_adjacent = any(
                state_elem not in ('X', 'U') and state_elem != str(self.player_id)
                for state_elem in [
                    self.state.elements[nr][nc]
                    for nr, nc in hex_neighbors(r, c)
                ]
            )
            # On accepte quand même si pas de meilleure option
            if enemy_adjacent and score < 50:
                continue

            if self._act(f"AJOUTERRECOLTEUSE|{r}|{c}"):
                log.info(f"  [ACHAT] Récolteuse ({r},{c}) score={score:.0f}")
                self.state.place_harvester(r, c)
                self.budget -= COST_HARVESTER
                n += 1
                occupied_this_turn.add((r, c))
                # Invalider les cases voisines pour éviter double-achat adjacent
                for nr, nc in hex_neighbors(r, c):
                    occupied_this_turn.add((nr, nc))

    # ── 4. Usines ──────────────────────────────────────────────────────────

    def _buy_factories(self, phase: str, turns_left: int):
        """Place des usines si ROI positif."""
        max_fact = FACTORY_TARGETS[phase]
        n_fact   = len(self.state.my_factories)

        if n_fact >= max_fact:
            return
        if self.budget < COST_FACTORY:
            return
        if not self.state.my_harvesters:
            return
        if self.cmds <= 1:
            return

        pos, roi = best_factory_position(self.state, turns_left)
        if pos is None:
            return

        # ROI doit être positif, sauf très tôt en partie
        if roi < 0 and self.state.turn > 15:
            log.debug(f"  [USINE] ROI négatif ({roi:.0f}), skip")
            return

        r, c = pos
        if self._act(f"AJOUTERUSINE|{r}|{c}"):
            log.info(f"  [USINE] ({r},{c}) ROI={roi:.0f}")
            self.state.place_factory(r, c)
            self.budget -= COST_FACTORY

    # ── 5. Repositionnement ────────────────────────────────────────────────

    def _reposition(self, dangerous: set):
        """Déplace les récolteuses peu rentables vers de meilleures positions."""
        if self.cmds <= 2:
            return

        candidates = []
        for r, c in list(self.state.my_harvesters):
            sector = get_sector(r, c)
            if sector in dangerous:
                continue
            inc = harvester_income(self.state, r, c)
            move, dest = should_relocate(self.state, r, c, threshold=1.35)
            if move and dest:
                candidates.append((r, c, dest[0], dest[1], inc))

        # Trier par gain décroissant (les moins rentables en premier)
        candidates.sort(key=lambda x: x[4])

        moved_dests = set()
        for r, c, nr, nc, inc in candidates[:3]:  # Max 3 repositionnements/tour
            if self.cmds <= 1:
                break
            if not self.state.is_free(nr, nc):
                continue
            if (nr, nc) in moved_dests:
                continue
            new_inc = marginal_income(self.state, nr, nc)
            if new_inc > inc * 1.35:
                if self._act(f"DEPLACER|{r}|{c}|{nr}|{nc}"):
                    log.info(f"  [REPOSITION] ({r},{c})→({nr},{nc}) "
                             f"{inc:.0f}→{new_inc:.0f}/tour")
                    self.state.move_harvester(r, c, nr, nc)
                    moved_dests.add((nr, nc))

    # ── 6. Sabotage ────────────────────────────────────────────────────────

    def _preview_sabotage_targets(self, turn: int, phase: str) -> set:
        """Retourne les secteurs qu'on prévoit de saboter ce tour (sans les exécuter)."""
        if self.budget < COST_SABOTAGE * 3:
            return set()
        targets = []
        for sector in range(4):
            if self.state.is_danger(sector):
                continue
            my = self.state.count_harvesters_in_sector(sector, self.player_id)
            if my > 0:
                continue
            val = sabotage_value(self.state, sector)
            if val <= 0:
                continue
            last = self.sabotaged.get(sector, -99)
            if turn - last < 3:
                continue
            min_enemies = 1 if phase == 'LATE' else 2
            enemy_count = self.state.count_harvesters_in_sector(sector) - my
            if enemy_count < min_enemies:
                continue
            targets.append((val, sector))
        targets.sort(reverse=True)
        max_sabotages = 2 if phase == 'LATE' else 1
        return {sector for _, sector in targets[:max_sabotages]}

    def _sabotage(self, turn: int, phase: str, condemned: set):
        """Sabote les secteurs ennemis les plus riches."""
        if self.cmds <= 1:
            return
        if self.budget < COST_SABOTAGE * 3:
            return

        targets = []
        for sector in range(4):
            if self.state.is_danger(sector):
                continue  # Inutile de saboter un secteur déjà sous attaque
            my = self.state.count_harvesters_in_sector(sector, self.player_id)
            if my > 0:
                continue  # Ne jamais saboter son propre secteur

            val = sabotage_value(self.state, sector)
            if val <= 0:
                continue

            last = self.sabotaged.get(sector, -99)
            if turn - last < 3:
                continue  # Cooldown

            # En LATE, harceler même les secteurs peu peuplés
            min_enemies = 1 if phase == 'LATE' else 2
            enemy_count = self.state.count_harvesters_in_sector(sector) - my
            if enemy_count < min_enemies:
                continue

            targets.append((val, sector, enemy_count))

        targets.sort(reverse=True)

        max_sabotages = 2 if phase == 'LATE' else 1
        for val, sector, count in targets[:max_sabotages]:
            if self.cmds <= 1:
                break
            if self.budget < COST_SABOTAGE:
                break
            if self._act(f"SABOTER|{sector}"):
                log.info(f"  [SABOTAGE] Secteur {sector} "
                         f"({count} ennemis, val={val:.0f})")
                self.sabotaged[sector] = turn
                self.budget -= COST_SABOTAGE
                condemned.add(sector)
