"""
Moteur stratégique For The Spice
- Valeur marginale réelle (partage hexagonal correct)
- Heatmap multi-facteurs
- ROI usines basé uniquement sur NOS récolteuses
- Repositionnement dynamique par gradient de densité
"""

from game_state import (
    GameState, hex_neighbors, hex_distance, get_sector,
    ROWS, COLS, SECTORS, cells_within_radius
)

COST_HARVESTER = 3000
COST_FACTORY   = 5000
COST_SABOTAGE  = 600   # CORRIGÉ : 600 (et non 500)


# ── Revenus ────────────────────────────────────────────────────────────────

def cell_base_production(state: GameState, r: int, c: int) -> float:
    """Production brute d'une case (avant partage). 0 si usine."""
    if state.elements[r][c] == 'U':
        return 0.0
    prod = state.density[r][c] * 10.0
    if state.has_factory_in_radius(r, c, 2):
        prod *= 2.0
    return prod


def harvesters_sharing_cell(state: GameState, r: int, c: int) -> int:
    """Nombre de récolteuses (tous joueurs) qui récoltent la case (r,c)."""
    count = 0
    if state.elements[r][c] not in ('X', 'U'):
        count += 1
    for nr, nc in hex_neighbors(r, c):
        if state.elements[nr][nc] not in ('X', 'U'):
            count += 1
    return count


def harvester_income(state: GameState, r: int, c: int) -> float:
    """Revenu réel par tour d'une récolteuse en (r,c), partage exact."""
    total = 0.0
    for hr, hc in [(r, c)] + hex_neighbors(r, c):
        if state.elements[hr][hc] == 'U':
            continue
        prod    = cell_base_production(state, hr, hc)
        sharing = harvesters_sharing_cell(state, hr, hc)
        if sharing > 0:
            total += prod / sharing
    return total


def marginal_income(state: GameState, r: int, c: int) -> float:
    """
    Gain marginal NET si on place une récolteuse en (r,c).
    Tient compte de la dilution qu'on inflige à nos propres récolteuses voisines.
    """
    if not state.is_free(r, c):
        return 0.0

    pid_str  = str(state.player_id)
    gain     = 0.0
    affected = [(r, c)] + hex_neighbors(r, c)

    for hr, hc in affected:
        if state.elements[hr][hc] == 'U':
            continue
        prod   = cell_base_production(state, hr, hc)
        before = harvesters_sharing_cell(state, hr, hc)
        after  = before + 1

        # Notre gain sur cette case
        gain += prod / after

        # Perte infligée à nos propres récolteuses voisines (dilution)
        for nr, nc in hex_neighbors(hr, hc):
            if state.elements[nr][nc] == pid_str and (nr, nc) != (r, c):
                if before > 0:
                    gain -= (prod / before - prod / after)

    return gain


# ── Densité : gradient et zones riches ────────────────────────────────────

def density_score_area(state: GameState, r: int, c: int, radius: int = 2) -> float:
    """Score de densité d'une zone : somme pondérée par distance inverse."""
    total = 0.0
    for nr, nc in cells_within_radius(r, c, radius):
        d      = hex_distance(r, c, nr, nc)
        weight = 1.0 / (d + 1)
        total += state.density[nr][nc] * weight
    return total


def find_density_peaks(state: GameState, top_n: int = 12) -> list:
    """
    Trouve les N meilleures zones de densité (non occupées, hors DANGER).
    Retourne [(r, c, score)] triée par score décroissant, avec espacement ≥ 3.
    """
    scored = []
    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c):
                continue
            if state.is_danger(get_sector(r, c)):
                continue
            scored.append((r, c, density_score_area(state, r, c, radius=2)))
    scored.sort(key=lambda x: x[2], reverse=True)

    peaks = []
    for r, c, score in scored:
        if all(hex_distance(r, c, pr, pc) > 3 for pr, pc, _ in peaks):
            peaks.append((r, c, score))
        if len(peaks) >= top_n:
            break
    return peaks


# ── Interactions multi-joueurs ─────────────────────────────────────────────

class EnemyProfile:
    """Profil d'un adversaire (positions, secteur dominant, centre)."""
    def __init__(self, player_id: int):
        self.player_id     = player_id
        self.positions     = []
        self.sector_counts = {}
        self.total_count   = 0
        self.dominant_sector = -1

    def update(self, positions: list, sector_counts: dict):
        self.positions     = positions
        self.sector_counts = sector_counts
        self.total_count   = sum(sector_counts.values())
        if sector_counts:
            self.dominant_sector = max(sector_counts, key=sector_counts.get)
        else:
            self.dominant_sector = -1

    def density_center(self) -> tuple:
        if not self.positions:
            return (ROWS // 2, COLS // 2)
        avg_r = sum(r for r, c in self.positions) / len(self.positions)
        avg_c = sum(c for r, c in self.positions) / len(self.positions)
        return (int(avg_r), int(avg_c))


def analyze_enemies(state: GameState) -> dict:
    """Analyse tous les adversaires. Retourne {player_id: EnemyProfile}."""
    profiles = {}
    pid_str  = str(state.player_id)

    for r in range(ROWS):
        for c in range(COLS):
            ch = state.elements[r][c]
            if ch in ('X', 'U') or ch == pid_str:
                continue
            try:
                eid = int(ch)
            except ValueError:
                continue
            if eid not in profiles:
                profiles[eid] = EnemyProfile(eid)

    for eid, profile in profiles.items():
        eid_str   = str(eid)
        positions = [(r, c) for r in range(ROWS) for c in range(COLS)
                     if state.elements[r][c] == eid_str]
        sec_counts = {}
        for r, c in positions:
            s = get_sector(r, c)
            sec_counts[s] = sec_counts.get(s, 0) + 1
        profile.update(positions, sec_counts)

    return profiles


def shadow_value(state: GameState, r: int, c: int, enemy_profiles: dict) -> float:
    """
    Valeur 'shadow' : être adjacent à une récolteuse ennemie sur zone riche
    nous permet de partager sa production gratuitement.
    """
    pid_str = str(state.player_id)
    bonus   = 0.0
    for nr, nc in hex_neighbors(r, c):
        ch = state.elements[nr][nc]
        if ch in ('X', 'U') or ch == pid_str:
            continue
        prod    = cell_base_production(state, nr, nc)
        sharing = harvesters_sharing_cell(state, nr, nc)
        bonus  += prod / (sharing + 1) * 0.7
    return bonus


def blocker_value(state: GameState, r: int, c: int, enemy_profiles: dict) -> float:
    """Valeur de blocage : se placer entre un ennemi et une zone dense."""
    if not enemy_profiles:
        return 0.0
    bonus = 0.0
    for _, profile in enemy_profiles.items():
        if profile.total_count == 0:
            continue
        ec_r, ec_c  = profile.density_center()
        local_dens  = density_score_area(state, r, c, radius=2)
        dist_enemy  = hex_distance(r, c, ec_r, ec_c)
        if dist_enemy <= 5 and local_dens > 12:
            bonus += local_dens * max(0, 5 - dist_enemy) * 0.4
    return bonus


def coexist_penalty(state: GameState, r: int, c: int) -> float:
    """Pénalité de co-existence dans un secteur surpeuplé d'ennemis."""
    sector          = get_sector(r, c)
    all_in_sector   = state.count_harvesters_in_sector(sector)
    my_in_sector    = state.count_harvesters_in_sector(sector, state.player_id)
    enemy_in_sector = all_in_sector - my_in_sector

    if enemy_in_sector <= 0:
        return 0.0
    if all_in_sector >= 8:
        return -30.0 * enemy_in_sector
    if enemy_in_sector >= 3:
        return -10.0 * enemy_in_sector
    return 0.0


# ── Repositionnement dynamique ─────────────────────────────────────────────

def dynamic_relocation_target(state: GameState, r: int, c: int,
                               density_peaks: list,
                               enemy_profiles: dict):
    """
    Cible de déplacement dynamique.
    Combine gradient densité, shadow, blocage, co-existence.
    Retourne (nr, nc, score) ou None si rester est optimal.
    """
    current_inc = harvester_income(state, r, c)
    best_dest   = None
    best_score  = current_inc * 1.2   # Seuil : 20% de gain pour bouger

    for pr, pc, _ in density_peaks:
        if not state.is_free(pr, pc):
            continue
        if state.is_danger(get_sector(pr, pc)):
            continue

        base        = marginal_income(state, pr, pc)
        if base <= 0:
            continue

        local_dens  = density_score_area(state, pr, pc, radius=2)
        current_dens = density_score_area(state, r, c, radius=2)
        dens_gain   = (local_dens - current_dens) * 2.0
        shd         = shadow_value(state, pr, pc, enemy_profiles)
        blk         = blocker_value(state, pr, pc, enemy_profiles)
        coex        = coexist_penalty(state, pr, pc)

        total = base + dens_gain + shd * 0.5 + blk * 0.3 + coex
        if total > best_score:
            best_score = total
            best_dest  = (pr, pc, total)

    return best_dest


# ── Heatmap ────────────────────────────────────────────────────────────────

SECTOR_CENTERS = [
    (3, 4),    # secteur 0 (NW)
    (3, 13),   # secteur 1 (NE)
    (12, 4),   # secteur 2 (SW)
    (12, 13),  # secteur 3 (SE)
]


def build_heatmap(state: GameState, turn: int, phase: str,
                  dangerous_sectors: set, condemned_sectors: set,
                  recently_safe: set = None, losing: bool = False,
                  enemy_profiles: dict = None,
                  density_peaks: list = None) -> list:
    """
    Heatmap des cases libres triée par score décroissant.
    Intègre toutes les tactiques : densité, shadow, blocage, co-existence,
    dispersion initiale, retour post-ver.
    """
    recently_safe  = recently_safe  or set()
    enemy_profiles = enemy_profiles or {}
    density_peaks  = density_peaks  or []

    all_factories     = {(r, c) for r in range(ROWS) for c in range(COLS)
                         if state.elements[r][c] == 'U'}
    allies_per_sector = {s: state.count_harvesters_in_sector(s, state.player_id)
                         for s in range(4)}

    if not density_peaks:
        density_peaks = find_density_peaks(state, top_n=12)
    peak_set = {(pr, pc) for pr, pc, _ in density_peaks}

    result = []
    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c):
                continue
            sector = get_sector(r, c)
            if sector in dangerous_sectors or sector in condemned_sectors:
                continue

            score = marginal_income(state, r, c)
            if score <= 0:
                continue

            # ── Boost densité ─────────────────────────────────────────
            local_density = density_score_area(state, r, c, radius=2)
            density_norm  = local_density / 76.0
            score *= (1.0 + density_norm * 1.5)

            if (r, c) in peak_set:
                score *= 1.4

            # ── Usine proche ──────────────────────────────────────────
            if all_factories:
                dist_fact = min(hex_distance(r, c, fr, fc) for fr, fc in all_factories)
                if dist_fact <= 2:
                    score *= 1.5

            # ── Shadow + blocage ──────────────────────────────────────
            score += shadow_value(state, r, c, enemy_profiles)
            score += blocker_value(state, r, c, enemy_profiles) * 0.4
            score += coexist_penalty(state, r, c)

            # ── Dispersion initiale (tours 1-3) ───────────────────────
            if turn <= 3:
                covered = {get_sector(hr, hc) for hr, hc in state.my_harvesters}
                if sector not in covered:
                    for sr, sc in SECTOR_CENTERS:
                        if get_sector(sr, sc) == sector:
                            if hex_distance(r, c, sr, sc) <= 3:
                                score *= 1.5
                            break

            # ── Retour post-attaque de ver ────────────────────────────
            if sector in recently_safe:
                score *= 1.3

            # ── Retard : pression sur zones ennemies ──────────────────
            if losing:
                enemy_in_sec = (state.count_harvesters_in_sector(sector)
                                - allies_per_sector[sector])
                if enemy_in_sec >= 2:
                    score *= 1.15

            # ── Anti-clustering ───────────────────────────────────────
            if allies_per_sector[sector] >= 6:
                score *= 0.4
            elif allies_per_sector[sector] >= 4:
                score *= 0.7
            elif allies_per_sector[sector] >= 2:
                score *= 0.9

            # ── Pénalité voisins ennemis directs ──────────────────────
            enemy_nbrs = sum(
                1 for nr, nc in hex_neighbors(r, c)
                if state.elements[nr][nc] not in ('X', 'U')
                and state.elements[nr][nc] != str(state.player_id)
            )
            score -= enemy_nbrs * 8

            result.append({
                'r': r, 'c': c, 'score': score,
                'sector': sector, 'density': local_density
            })

    result.sort(key=lambda x: x['score'], reverse=True)
    return result


# ── Usines ─────────────────────────────────────────────────────────────────

def factory_roi(state: GameState, r: int, c: int, turns_left: int) -> float:
    """
    ROI d'une usine en (r,c) sur les tours restants.
    CORRECTION : on ne comptabilise que les cases où NOS récolteuses récoltent
    (pas les gains qui iraient aux ennemis).
    """
    if not state.is_free(r, c):
        return -1.0

    pid_str      = str(state.player_id)
    gain_per_turn = 0.0

    for ar, ac in cells_within_radius(r, c, 2):
        if (ar, ac) == (r, c):
            continue
        if state.elements[ar][ac] == 'U':
            continue
        if state.has_factory_in_radius(ar, ac, 2):
            continue   # Usine déjà présente → pas de bonus supplémentaire

        # Ne compter que si au moins une de NOS récolteuses récolte cette case
        adjacent_ours = state.elements[ar][ac] == pid_str or any(
            state.elements[nr][nc] == pid_str
            for nr, nc in hex_neighbors(ar, ac)
        )
        if not adjacent_ours:
            continue

        sharing = harvesters_sharing_cell(state, ar, ac)
        if sharing > 0:
            # Gain = doublement de la production / sharing (notre part)
            gain_per_turn += (state.density[ar][ac] * 10.0) / sharing

    return gain_per_turn * turns_left - COST_FACTORY


def best_factory_position(state: GameState, turns_left: int):
    """Meilleure position pour une usine (ROI max, hors secteur DANGER)."""
    best_pos = None
    best_roi = 0.0

    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c):
                continue
            if state.is_danger(get_sector(r, c)):
                continue
            roi = factory_roi(state, r, c, turns_left)
            if roi > best_roi:
                best_roi = roi
                best_pos = (r, c)

    return best_pos, best_roi


# ── Sabotage ───────────────────────────────────────────────────────────────

def sabotage_value(state: GameState, sector: int) -> float:
    """
    Valeur d'un sabotage sur ce secteur.
    = nombre de récolteuses ennemies détruites × COST_HARVESTER − COST_SABOTAGE.
    Retourne -9999 si on a des unités dans ce secteur (auto-protection).
    """
    my_count = state.count_harvesters_in_sector(sector, state.player_id)
    if my_count > 0:
        return -9999.0

    enemy_count = 0
    for r, c in state.harvesters_in_sector(sector):
        if state.elements[r][c] != str(state.player_id):
            enemy_count += 1

    return enemy_count * COST_HARVESTER - COST_SABOTAGE


# ── Repositionnement ───────────────────────────────────────────────────────

def should_relocate(state: GameState, r: int, c: int,
                    threshold: float = 1.2,
                    density_peaks: list = None,
                    enemy_profiles: dict = None) -> tuple:
    """
    Détermine si une récolteuse devrait changer de case.
    Retourne (True, (nr, nc)) ou (False, None).
    """
    density_peaks  = density_peaks  or []
    enemy_profiles = enemy_profiles or {}

    current_income = harvester_income(state, r, c)

    # Revenu nul → déplacer immédiatement vers la meilleure case libre
    if current_income <= 0:
        best = _find_best_free(state, exclude={(r, c)})
        return (True, best) if best else (False, None)

    # Cible dynamique basée sur gradient densité
    dest = dynamic_relocation_target(state, r, c, density_peaks, enemy_profiles)
    if dest is not None:
        nr, nc, _ = dest
        return (True, (nr, nc))

    # Fallback scan classique
    best_pos  = None
    best_gain = current_income * threshold

    for nr in range(ROWS):
        for nc in range(COLS):
            if not state.is_free(nr, nc):
                continue
            if state.is_danger(get_sector(nr, nc)):
                continue
            val = marginal_income(state, nr, nc)
            if val > best_gain:
                best_gain = val
                best_pos  = (nr, nc)

    return (True, best_pos) if best_pos else (False, None)


def _find_best_free(state: GameState, avoid_sectors=None, exclude=None):
    """Case libre la plus rentable (marginal_income), hors secteurs à éviter."""
    avoid_sectors = avoid_sectors or set()
    exclude       = exclude or set()
    best     = None
    best_val = -1

    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c): continue
            if (r, c) in exclude: continue
            sector = get_sector(r, c)
            if sector in avoid_sectors or state.is_danger(sector): continue
            val = marginal_income(state, r, c)
            if val > best_val:
                best_val = val
                best     = (r, c)
    return best


def total_income(state: GameState) -> float:
    """Revenu total estimé de toutes nos récolteuses."""
    return sum(harvester_income(state, r, c) for r, c in state.my_harvesters)
