"""
Cerveau Elite — For The Spice
Stratégie adaptative par phase + toutes les optimisations fusionnées.

Ordre de priorité strict par tour (15 commandes max + FINDETOUR):
  0. Collecte d'info  (2-3 cmds : ELEMENTS, WARNING, SCORES — DENSITE tous les 20 tours)
  1. Survie           : évacuer récolteuses en secteur DANGER
  2. Vision           : ornithoptères dans les 4 secteurs (renouvelés toutes les 4 tours)
  3. Expansion        : achat récolteuses via heatmap densité
  4. Industrie        : usines si ROI positif
  5. Repositionnement : gradient densité dynamique
  6. Sabotage         : frappe secteurs ennemis concentrés
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
COST_SABOTAGE  = 600   # manuel : 600 unités
ORNI_REFRESH   = 4     # ornithoptère dure 5 tours → renouveler à 4

# Plafond de récolteuses par phase
TARGETS = {
    'EARLY': 8,   # agressif dès le départ (budget initial ~1M)
    'MID':   12,
    'LATE':  12,
}
FACTORY_TARGETS = {
    'EARLY': 1,
    'MID':   3,
    'LATE':  3,
}

# Tours où on ne dépense rien (garder l'épice pour le score final)
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

        self.orni_deployed   = {}   # secteur → dernier tour de déploiement
        self.sabotaged       = {}   # secteur → dernier tour de sabotage
        self.density_fetched = False

        # Cache pics de densité (recalculé tous les 5 tours)
        self._density_peaks      = []
        self._density_peaks_turn = -99

        # Profils ennemis mis à jour chaque tour
        self._enemy_profiles = {}

        # Compteur de commandes restantes (15 max + FINDETOUR)
        self.cmds   = 0
        self.budget = 0

    # ── Interface publique ─────────────────────────────────────────────────

    def play_turn(self, turn: int):
        self.state.turn = turn
        self.cmds = 14   # 14 actions + 1 FINDETOUR = 15 commandes au total
        phase = get_phase(turn)
        turns_left = 200 - turn

        # ── 0. COLLECTE D'INFO ────────────────────────────────────────────
        self._fetch_elements()                                 # toujours
        if not self.density_fetched or turn % 20 == 1:
            self._fetch_density()                              # 1er tour + tous les 20
        self._fetch_warnings()                                 # toujours
        if turn % 5 == 1:
            self._fetch_scores()                               # tous les 5 tours suffit

        self.budget = self.state.my_score()
        my_sc   = self.state.my_score()
        enemy_sc = self.state.max_enemy_score()
        losing  = enemy_sc > my_sc * 1.05   # 5% de marge avant de considérer qu'on perd
        n_harv  = len(self.state.my_harvesters)
        n_fact  = len(self.state.my_factories)
        inc     = total_income(self.state)

        log.warning(
            f"[{phase}] T{turn} | Budget:{self.budget} | H:{n_harv} | "
            f"F:{n_fact} | Inc:{inc:.0f}/t | "
            f"Nous:{my_sc} Eux:{enemy_sc} | Cmds:{self.cmds}"
        )
        log.warning(f"Warnings: {self.state.warnings}")

        # Catégories de secteurs
        dangerous    = {s for s in range(4) if self.state.is_danger(s)}
        recently_safe = {
            s for s in range(4)
            if self.state.recently_attacked(s, turn, cooldown=15)
            and s not in dangerous
        }
        condemned = set()

        # ── Tours finaux : uniquement FINDETOUR ───────────────────────────
        if turn in NO_SPEND_TURNS:
            log.warning(f"Tour final {turn}: pas de dépenses")
            self.net.send_findetour()
            return

        # ── Analyse contextuelle (pré-calcul partagé) ─────────────────────
        self._enemy_profiles = analyze_enemies(self.state)
        self._log_enemies()

        if turn - self._density_peaks_turn >= 5:
            self._density_peaks = find_density_peaks(self.state, top_n=12)
            self._density_peaks_turn = turn
            top = self._density_peaks[0] if self._density_peaks else None
            log.warning(f"  [DENSITY] {len(self._density_peaks)} pics, top={top}")

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
        max_h = self._dynamic_max_harvesters(phase, turns_left, losing)
        self._buy_harvesters(heatmap, phase, turns_left, max_h)

        # ── 4. INDUSTRIE ──────────────────────────────────────────────────
        if phase != 'LATE' or n_fact < FACTORY_TARGETS['LATE']:
            self._buy_factories(phase, turns_left)

        # ── 5. REPOSITIONNEMENT DYNAMIQUE ─────────────────────────────────
        if turn >= 5:
            self._reposition_dynamic(dangerous)

        # ── 6. SABOTAGE ───────────────────────────────────────────────────
        self._sabotage(turn, phase, condemned, losing)

        # ── 7. FIN DE TOUR ────────────────────────────────────────────────
        self.net.send_findetour()
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
                log.warning(
                    f"  [ENNEMI {eid}] {p.total_count} récolt. | "
                    f"secteur:{p.dominant_sector} | centre:{p.density_center()}"
                )

    # ── Action sécurisée ───────────────────────────────────────────────────

    def _act(self, cmd: str) -> bool:
        """Envoie une action si des commandes restent. Décrémente le compteur."""
        if self.cmds <= 0:
            return False
        ok = self.net.send_action(cmd)
        self.cmds -= 1
        return ok

    # ── Plafond dynamique récolteuses ──────────────────────────────────────

    def _dynamic_max_harvesters(self, phase: str, turns_left: int, losing: bool) -> int:
        base = TARGETS[phase]
        # En retard et avec du budget → être encore plus agressif
        if losing and self.budget > COST_HARVESTER * 4:
            base = min(base + 3, 15)
        # Si on est très en dessous du plafond → accélérer l'expansion
        n_harv = len(self.state.my_harvesters)
        if n_harv < base - 3 and self.budget > COST_HARVESTER * 3:
            base = min(base + 2, 15)
        return base

    # ── 1. Survie ──────────────────────────────────────────────────────────

    def _evacuate(self, dangerous: set):
        """Évacue toutes les récolteuses dans les secteurs DANGER."""
        moved = set()
        for r, c in list(self.state.my_harvesters):
            if self.cmds <= 0:
                break
            if get_sector(r, c) not in dangerous:
                continue

            dest = _find_best_free(
                self.state, avoid_sectors=dangerous, exclude=moved | {(r, c)}
            )
            if dest is None:
                # Fallback brut : première case libre hors danger
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
        """
        Déploie des ornithoptères dans TOUS les secteurs, pas seulement les actifs.
        Priorité : actifs > ennemis concentrés > récemment sûrs > inconnus.
        Orni dure 5 tours → renouvellement à 4 tours.
        """
        active_sectors = {get_sector(r, c) for r, c in self.state.my_harvesters}
        enemy_dominant = {
            p.dominant_sector for p in self._enemy_profiles.values()
            if p.dominant_sector >= 0 and p.total_count >= 2
        }

        # Ordre de priorité
        ordered = list(active_sectors)
        for s in enemy_dominant:
            if s not in ordered: ordered.append(s)
        for s in recently_safe:
            if s not in ordered: ordered.append(s)
        # Toujours couvrir les 4 secteurs (vision complète = +EV garanti)
        for s in range(4):
            if s not in ordered: ordered.append(s)

        for sector in ordered:
            if self.cmds <= 0:
                break
            last = self.orni_deployed.get(sector, -999)
            if turn - last >= ORNI_REFRESH:
                if self._act(f"AJOUTERORNI|{sector}"):
                    self.orni_deployed[sector] = turn
                    log.warning(f"  [ORNI] Secteur {sector}")

    # ── 3. Achats récolteuses ──────────────────────────────────────────────

    def _buy_harvesters(self, heatmap: list, phase: str, turns_left: int, max_h: int):
        """
        Achète des récolteuses sur les meilleures cases de la heatmap.
        Vérifie ROI minimum, budget, et évite le clustering.
        """
        n = len(self.state.my_harvesters)
        # Tours 1-5 : forcer l'expansion initiale (au moins 4 récolteuses)
        if self.state.turn <= 5:
            max_h = max(max_h, min(4, 4))

        occupied_this_turn = set()

        for entry in heatmap:
            if self.cmds <= 0: break
            if n >= max_h: break
            if self.budget < COST_HARVESTER: break

            r, c = entry['r'], entry['c']
            if (r, c) in occupied_this_turn or not self.state.is_free(r, c):
                continue

            score = entry['score']

            # ROI minimum : le gain sur les tours restants doit couvrir le coût
            # (désactivé pour les 10 premiers tours pour garantir l'expansion)
            if turns_left > 0 and score * turns_left < COST_HARVESTER and self.state.turn > 10:
                break

            if self._act(f"AJOUTERRECOLTEUSE|{r}|{c}"):
                dens = entry.get('density', 0)
                log.warning(f"  [ACHAT] ({r},{c}) score={score:.0f} dens={dens:.1f}")
                self.state.place_harvester(r, c)
                self.budget -= COST_HARVESTER
                n += 1
                occupied_this_turn.add((r, c))
                # Marquer les voisins pour éviter le clustering immédiat
                for nr, nc in hex_neighbors(r, c):
                    occupied_this_turn.add((nr, nc))

    # ── 4. Usines ──────────────────────────────────────────────────────────

    def _buy_factories(self, phase: str, turns_left: int):
        """Place une usine si le ROI est positif et qu'on a les fonds."""
        max_fact = FACTORY_TARGETS[phase]
        n_fact   = len(self.state.my_factories)
        if n_fact >= max_fact:  return
        if self.budget < COST_FACTORY: return
        if not self.state.my_harvesters or self.cmds <= 0: return

        pos, roi = best_factory_position(self.state, turns_left)
        if pos is None:
            return

        # Tours < 15 : accepter ROI légèrement négatif (investissement long terme)
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
        Repositionnement par gradient de densité.
        Les récolteuses les moins rentables bougent en premier.
        Seuil abaissé à ×1.15 (très réactif).
        """
        if self.cmds <= 1:
            return

        candidates = []
        for r, c in list(self.state.my_harvesters):
            if get_sector(r, c) in dangerous:
                continue
            inc = harvester_income(self.state, r, c)
            move, dest = should_relocate(
                self.state, r, c,
                threshold=1.2,
                density_peaks=self._density_peaks,
                enemy_profiles=self._enemy_profiles
            )
            if move and dest:
                candidates.append((r, c, dest[0], dest[1], inc))

        # Les moins rentables bougent en premier
        candidates.sort(key=lambda x: x[4])

        moved_dests = set()
        for r, c, nr, nc, inc in candidates[:4]:
            if self.cmds <= 0: break
            if not self.state.is_free(nr, nc): continue
            if (nr, nc) in moved_dests: continue

            new_inc = marginal_income(self.state, nr, nc)
            if new_inc > inc * 1.15:
                if self._act(f"DEPLACER|{r}|{c}|{nr}|{nc}"):
                    dens = density_score_area(self.state, nr, nc)
                    log.warning(
                        f"  [MOVE] ({r},{c})→({nr},{nc}) "
                        f"inc:{inc:.0f}→{new_inc:.0f} dens:{dens:.1f}"
                    )
                    self.state.move_harvester(r, c, nr, nc)
                    moved_dests.add((nr, nc))

    # ── 6. Sabotage ────────────────────────────────────────────────────────

    def _sabotage(self, turn: int, phase: str, condemned: set, losing: bool):
        """
        Sabotage ciblé :
        - Secteurs avec le plus de récolteuses ennemies (hors nos présences)
        - Cooldown 3 tours pour ne pas gaspiller
        - En LATE / retard : mode harcèlement (1 ennemi suffit)
        - Budget minimum 3× COST_SABOTAGE pour ne pas se retrouver à sec
        """
        if self.cmds <= 0 or self.budget < COST_SABOTAGE * 3:
            return

        targets = []
        for sector in range(4):
            # Jamais saboter si on a des unités dans le secteur
            if self.state.count_harvesters_in_sector(sector, self.player_id) > 0:
                continue
            if self.state.is_danger(sector):
                continue

            val = sabotage_value(self.state, sector)
            if val <= 0:
                continue

            # Cooldown
            last = self.sabotaged.get(sector, -99)
            if turn - last < 3:
                continue

            aggressive = losing or phase == 'LATE'
            min_enemies = 1 if aggressive else 2
            enemy_count = self.state.count_harvesters_in_sector(sector) - \
                          self.state.count_harvesters_in_sector(sector, self.player_id)
            if enemy_count < min_enemies:
                continue

            # Bonus si l'ennemi dominant est concentré là
            dominant_bonus = sum(
                1 for p in self._enemy_profiles.values()
                if p.dominant_sector == sector and p.total_count >= 3
            )

            targets.append((val + dominant_bonus * 2000, sector, enemy_count))

        targets.sort(reverse=True)

        max_sabotages = 3 if losing else (2 if phase == 'LATE' else 1)
        for val, sector, count in targets[:max_sabotages]:
            if self.cmds <= 0 or self.budget < COST_SABOTAGE:
                break
            if self._act(f"SABOTER|{sector}"):
                log.warning(f"  [SABOTAGE] Secteur {sector} ({count} ennemis, val={val:.0f})")
                self.sabotaged[sector] = turn
                self.budget -= COST_SABOTAGE
                condemned.add(sector)
