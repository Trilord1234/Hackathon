"""
Cerveau Elite - For The Spice
Stratégie adaptative par phase + toutes les optimisations fusionnées.

Ordre de priorité strict par tour:
  0. Collecte d'info (4 cmds)
  1. Survie: évacuer les récolteuses en danger (DANGER warning)
  2. Vision: renouveler ornithoptères dans secteurs actifs
  3. Expansion: acheter récolteuses (heatmap density-aware + multi-joueurs)
  4. Industrie: placer usines (ROI positif)
  5. Optimisation: repositionnement dynamique par gradient de densité
  6. Sabotage: cibler intelligemment selon les profils ennemis
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
    should_relocate, total_income, _find_best_free,
    analyze_enemies, find_density_peaks, density_score_area,
    EnemyProfile
)

log = logging.getLogger(__name__)

COST_HARVESTER = 3000
COST_FACTORY   = 5000
<<<<<<< Updated upstream
=======
<<<<<<< HEAD
COST_SABOTAGE  = 600
ORNI_REFRESH   = 4
=======
>>>>>>> Stashed changes
COST_ORNI      = 400
COST_SABOTAGE  = 500
ORNI_REFRESH   = 4   # Renouveler toutes les 4 tours (orni dure 5 tours)
>>>>>>> f2a5c98b7dc9835c553043c2fc2fecf1ba13aaa2

TARGETS = {
    'EARLY': 5,
    'MID':   8,
    'LATE':  0,
}
FACTORY_TARGETS = {
    'EARLY': 1,
    'MID':   3,
    'LATE':  3,
}

NO_SPEND_TURNS = {199, 200}


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

        self.orni_deployed   = {}
        self.sabotaged       = {}
        self.density_fetched = False

        # Cache pics de densité (recalculé tous les 5 tours)
        self._density_peaks      = []
        self._density_peaks_turn = -99

        # Profils ennemis (mis à jour chaque tour)
        self._enemy_profiles = {}

        self.cmds   = 0
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

        self.budget  = self.state.my_score()
        my_sc        = self.state.my_score()
        enemy_sc     = self.state.max_enemy_score()
        losing       = enemy_sc > my_sc
        n_harv       = len(self.state.my_harvesters)
        n_fact       = len(self.state.my_factories)
        inc          = total_income(self.state)

        log.warning(f"[{phase}] T{turn} | Budget:{self.budget} | H:{n_harv} | "
                    f"F:{n_fact} | Income:{inc:.0f}/t | "
                    f"Nous:{my_sc} Eux:{enemy_sc} | Cmds:{self.cmds}")
        log.warning(f"Warnings: {self.state.warnings}")

        # Secteurs dangereux / récemment attaqués
        dangerous     = {s for s in range(4) if self.state.is_danger(s)}
        recently_safe = {
            s for s in range(4)
            if self.state.recently_attacked(s, turn, cooldown=15)
            and s not in dangerous
        }
        condemned = set()

        # ── DERNIER TOUR ──────────────────────────────────────────────────
        if turn in NO_SPEND_TURNS:
            log.warning(f"Tour final {turn}: pas de dépenses")
            self.net.send("FINDETOUR")
            return

        # ── Analyse des ennemis + pics de densité (pré-calcul partagé) ───
        self._enemy_profiles = analyze_enemies(self.state)
        self._log_enemies()

        # Pics de densité: recalcul tous les 5 tours
        if turn - self._density_peaks_turn >= 5:
            self._density_peaks = find_density_peaks(self.state, top_n=10)
            self._density_peaks_turn = turn
            log.warning(f"  [DENSITY] {len(self._density_peaks)} pics, "
                        f"top={self._density_peaks[0] if self._density_peaks else None}")

        # ── 1. SURVIE ─────────────────────────────────────────────────────
        self._evacuate(dangerous)

        # ── 2. VISION ─────────────────────────────────────────────────────
        self._deploy_ornis(turn, recently_safe)

        # ── 3. EXPANSION ──────────────────────────────────────────────────
        heatmap = build_heatmap(
            self.state, turn, phase, dangerous, condemned,
            recently_safe=recently_safe, losing=losing,
            enemy_profiles=self._enemy_profiles,
            density_peaks=self._density_peaks
        )
        if phase != 'LATE':
            max_h = self._dynamic_max_harvesters(phase, turns_left, losing)
            self._buy_harvesters(heatmap, phase, turns_left, max_h)

        # ── 4. INDUSTRIE ──────────────────────────────────────────────────
        if phase != 'LATE':
            self._buy_factories(phase, turns_left)

        # ── 5. REPOSITIONNEMENT DYNAMIQUE ─────────────────────────────────
        if turn >= 10:
            self._reposition_dynamic(dangerous)

        # ── 6. SABOTAGE ───────────────────────────────────────────────────
        self._sabotage(turn, phase, condemned, losing)

        # ── 7. FIN DE TOUR ────────────────────────────────────────────────
        self.net.send("FINDETOUR")
        log.warning(f"FIN T{turn} | Cmds restantes: {self.cmds}")

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

    # ── Logging ────────────────────────────────────────────────────────────

    def _log_enemies(self):
        for eid, p in self._enemy_profiles.items():
            if p.total_count > 0:
                log.warning(f"  [ENNEMI {eid}] {p.total_count} récolt. | "
                            f"secteur dominant:{p.dominant_sector} | "
                            f"centre:({p.density_center()})")

    # ── Action helpers ─────────────────────────────────────────────────────

    def _act(self, cmd) -> bool:
        if self.cmds <= 1:
            return False
        ok = self.net.send_action(cmd)
        self.cmds -= 1
        return ok

    # ── Calcul dynamique du plafond ────────────────────────────────────────

    def _dynamic_max_harvesters(self, phase: str, turns_left: int, losing: bool) -> int:
        base = TARGETS[phase]
        if losing and self.budget > COST_HARVESTER * 3:
            base = min(base + 2, 10)
        n_harv = len(self.state.my_harvesters)
        if n_harv < base - 2 and self.budget > COST_HARVESTER * 2:
            base = min(base + 1, 10)
        return base

    # ── 1. Survie ──────────────────────────────────────────────────────────

    def _evacuate(self, dangerous: set):
        moved = set()
        for r, c in list(self.state.my_harvesters):
            if self.cmds <= 1:
                break
            sector = get_sector(r, c)
            if sector not in dangerous:
                continue

            dest = _find_best_free(
                self.state, avoid_sectors=dangerous, exclude=moved | {(r, c)}
            )
            if dest is None:
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
                    log.warning(f"  [SURVIE] ({r},{c}) → ({nr},{nc})")
                    self.state.move_harvester(r, c, nr, nc)
                    moved.add((nr, nc))

    # ── 2. Ornithoptères ───────────────────────────────────────────────────

    def _deploy_ornis(self, turn: int, recently_safe: set):
        """Déploie des ornithoptères dans secteurs actifs + récemment libérés.
        Priorité aux secteurs ennemis denses (pour surveiller le shadow)."""
        active_sectors = {get_sector(r, c) for r, c in self.state.my_harvesters}

        # Secteurs ennemis dominants (pour détecter mouvements adverses)
        enemy_dominant = {p.dominant_sector for p in self._enemy_profiles.values()
                          if p.dominant_sector >= 0 and p.total_count >= 3}

        watch_sectors = active_sectors | recently_safe | enemy_dominant

        # Trier: actifs d'abord, puis ennemis, puis recently_safe
        ordered = (list(active_sectors) +
                   [s for s in enemy_dominant if s not in active_sectors] +
                   [s for s in recently_safe if s not in active_sectors | enemy_dominant])

        for sector in ordered:
            if self.cmds <= 1:
                break
            last = self.orni_deployed.get(sector, -999)
            if turn - last >= ORNI_REFRESH:
                if self._act(f"AJOUTERORNI|{sector}"):
                    self.orni_deployed[sector] = turn
                    log.warning(f"  [ORNI] Secteur {sector}")

    # ── 3. Achats récolteuses ──────────────────────────────────────────────

    def _buy_harvesters(self, heatmap: list, phase: str, turns_left: int, max_h: int):
        n = len(self.state.my_harvesters)
        if self.state.turn <= 3:
            max_h = max(max_h, 4)

        occupied_this_turn = set()

        for entry in heatmap:
            if self.cmds <= 1: break
            if n >= max_h: break
            if self.budget < COST_HARVESTER: break

            r, c = entry['r'], entry['c']
            if (r, c) in occupied_this_turn or not self.state.is_free(r, c):
                continue

            score = entry['score']
            if turns_left > 0 and score * turns_left < COST_HARVESTER and self.state.turn > 10:
                break

            enemy_adjacent = any(
                self.state.elements[nr][nc] not in ('X', 'U')
                and self.state.elements[nr][nc] != str(self.player_id)
                for nr, nc in hex_neighbors(r, c)
            )
            # Tolérer les voisins ennemis si la zone est dense (shadow profitable)
            local_dens = entry.get('density', 0)
            if enemy_adjacent and score < 50 and local_dens < 15:
                continue

            if self._act(f"AJOUTERRECOLTEUSE|{r}|{c}"):
                log.warning(f"  [ACHAT] ({r},{c}) score={score:.0f} dens={local_dens:.1f}")
                self.state.place_harvester(r, c)
                self.budget -= COST_HARVESTER
                n += 1
                occupied_this_turn.add((r, c))
                for nr, nc in hex_neighbors(r, c):
                    occupied_this_turn.add((nr, nc))

    # ── 4. Usines ──────────────────────────────────────────────────────────

    def _buy_factories(self, phase: str, turns_left: int):
        max_fact = FACTORY_TARGETS[phase]
        n_fact   = len(self.state.my_factories)
        if n_fact >= max_fact or self.budget < COST_FACTORY:
            return
        if not self.state.my_harvesters or self.cmds <= 1:
            return

        pos, roi = best_factory_position(self.state, turns_left)
        if pos is None:
            return
        if roi < 0 and self.state.turn > 15:
            log.warning(f"  [USINE] ROI négatif ({roi:.0f}), skip")
            return

        r, c = pos
        if self._act(f"AJOUTERUSINE|{r}|{c}"):
            log.warning(f"  [USINE] ({r},{c}) ROI={roi:.0f}")
            self.state.place_factory(r, c)
            self.budget -= COST_FACTORY

    # ── 5. Repositionnement dynamique ──────────────────────────────────────

    def _reposition_dynamic(self, dangerous: set):
        """
        Repositionnement dynamique: chaque récolteuse suit le gradient de densité
        et adapte sa position aux mouvements des adversaires.
        """
        if self.cmds <= 2:
            return

        candidates = []
        for r, c in list(self.state.my_harvesters):
            sector = get_sector(r, c)
            if sector in dangerous:
                continue
            inc = harvester_income(self.state, r, c)
            move, dest = should_relocate(
                self.state, r, c,
                threshold=1.2,  # seuil plus bas = mouvements plus réactifs
                density_peaks=self._density_peaks,
                enemy_profiles=self._enemy_profiles
            )
            if move and dest:
                candidates.append((r, c, dest[0], dest[1], inc))

        # Trier par revenu croissant (les moins rentables bougent en premier)
        candidates.sort(key=lambda x: x[4])

        moved_dests = set()
        for r, c, nr, nc, inc in candidates[:3]:
            if self.cmds <= 1:
                break
            if not self.state.is_free(nr, nc):
                continue
            if (nr, nc) in moved_dests:
                continue
            new_inc = marginal_income(self.state, nr, nc)
            # Seuil réduit à 1.2 (vs 1.35) pour être plus réactif à la densité
            if new_inc > inc * 1.15:
                if self._act(f"DEPLACER|{r}|{c}|{nr}|{nc}"):
                    log.warning(f"  [MOVE] ({r},{c})→({nr},{nc}) "
                                f"inc:{inc:.0f}→{new_inc:.0f} "
                                f"dens:{density_score_area(self.state, nr, nc):.1f}")
                    self.state.move_harvester(r, c, nr, nc)
                    moved_dests.add((nr, nc))

    # ── 6. Sabotage ────────────────────────────────────────────────────────

    def _sabotage(self, turn: int, phase: str, condemned: set, losing: bool):
        """
        Sabotage intelligent basé sur les profils ennemis:
        - Priorité aux secteurs où l'ennemi dominant est fort
        - En retard: sabotage agressif multi-cible
        - Coordination: ne pas saboter un secteur où on vient de se placer (shadow)
        """
        if self.cmds <= 1 or self.budget < COST_SABOTAGE * 3:
            return

        targets = []
        for sector in range(4):
            if self.state.is_danger(sector):
                continue
            my = self.state.count_harvesters_in_sector(sector, self.player_id)
            if my > 0:
                continue  # Ne jamais saboter son propre secteur

            val = sabotage_value(self.state, sector)
            if val <= 0:
                continue

            last = self.sabotaged.get(sector, -99)
            if turn - last < 3:
                continue

            aggressive = losing or phase == 'LATE'
            min_enemies = 1 if aggressive else 2
            enemy_count = self.state.count_harvesters_in_sector(sector) - my
            if enemy_count < min_enemies:
                continue

            # Bonus: si l'ennemi dominant est dans ce secteur → priorité sabotage
            dominant_bonus = 0
            for eid, p in self._enemy_profiles.items():
                if p.dominant_sector == sector and p.total_count >= 3:
                    dominant_bonus = 1
                    break

            targets.append((val + dominant_bonus * 2000, sector, enemy_count))

        targets.sort(reverse=True)

        max_sabotages = 3 if losing else (2 if phase == 'LATE' else 1)
        for val, sector, count in targets[:max_sabotages]:
            if self.cmds <= 1 or self.budget < COST_SABOTAGE:
                break
            if self._act(f"SABOTER|{sector}"):
                log.warning(f"  [SABOTAGE] Secteur {sector} "
                            f"({count} ennemis, val={val:.0f})")
                self.sabotaged[sector] = turn
                self.budget -= COST_SABOTAGE
                condemned.add(sector)
