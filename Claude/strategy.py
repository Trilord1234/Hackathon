"""
Moteur stratégique For The Spice
- Valeur marginale réelle (partage hexagonal)
- Heatmap avec tactiques avancées
- Mouvement dynamique basé sur gradient de densité
- Comportements multi-joueurs: shadowing, blocage, co-existence
"""

from game_state import (
    GameState, hex_neighbors, hex_distance, get_sector,
    ROWS, COLS, SECTORS, cells_within_radius
)

COST_HARVESTER = 3000
COST_FACTORY   = 5000
COST_SABOTAGE  = 500


# ── Revenus ────────────────────────────────────────────────────────────────

def cell_base_production(state: GameState, r: int, c: int) -> float:
    """Production brute d'une case (avant partage), 0 si usine."""
    if state.elements[r][c] == 'U':
        return 0.0
    prod = state.density[r][c] * 10.0
    if state.has_factory_in_radius(r, c, 2):
        prod *= 2.0
    return prod


def harvesters_sharing_cell(state: GameState, r: int, c: int) -> int:
    """Nombre de récolteuses qui récoltent la case (r,c)."""
    count = 0
    if state.elements[r][c] not in ('X', 'U'):
        count += 1
    for nr, nc in hex_neighbors(r, c):
        if state.elements[nr][nc] not in ('X', 'U'):
            count += 1
    return count


def harvester_income(state: GameState, r: int, c: int) -> float:
    """Revenu réel par tour d'une récolteuse en (r,c) avec partage exact."""
    total = 0.0
    for hr, hc in [(r, c)] + hex_neighbors(r, c):
        if state.elements[hr][hc] == 'U':
            continue
        prod = cell_base_production(state, hr, hc)
        sharing = harvesters_sharing_cell(state, hr, hc)
        if sharing > 0:
            total += prod / sharing
    return total


def marginal_income(state: GameState, r: int, c: int) -> float:
    """
    Gain marginal réel si on place une récolteuse en (r,c).
    Tient compte de la dilution chez les voisins.
    """
    if not state.is_free(r, c):
        return 0.0

    gain = 0.0
    affected = [(r, c)] + hex_neighbors(r, c)

    for hr, hc in affected:
        if state.elements[hr][hc] == 'U':
            continue
        prod = cell_base_production(state, hr, hc)
        before = harvesters_sharing_cell(state, hr, hc)
        after  = before + 1

        gain += prod / after

        for nr, nc in hex_neighbors(hr, hc):
            if state.elements[nr][nc] == str(state.player_id) and (nr, nc) != (r, c):
                if before > 0:
                    gain -= (prod / before - prod / after)

    return gain


# ── Densité: gradient et zones riches ─────────────────────────────────────

def density_gradient(state: GameState, r: int, c: int) -> tuple:
    """
    Calcule le gradient de densité autour de (r,c): direction + magnitude.
    Retourne (dr, dc, magnitude) — direction vers la zone la plus dense.
    La direction est un vecteur normalisé vers le centroïde pondéré des voisins.
    """
    best_r, best_c, best_density = r, c, state.density[r][c]
    # Chercher dans un rayon 3 la zone la plus dense non occupée
    for radius in range(1, 4):
        for nr, nc in cells_within_radius(r, c, radius):
            if (nr, nc) == (r, c):
                continue
            if not state.is_free(nr, nc):
                continue
            if state.density[nr][nc] > best_density:
                best_density = state.density[nr][nc]
                best_r, best_c = nr, nc
    mag = best_density - state.density[r][c]
    return (best_r - r, best_c - c, mag)


def density_score_area(state: GameState, r: int, c: int, radius: int = 2) -> float:
    """Score de densité d'une zone: somme pondérée par distance inverse."""
    total = 0.0
    for nr, nc in cells_within_radius(r, c, radius):
        d = hex_distance(r, c, nr, nc)
        weight = 1.0 / (d + 1)
        total += state.density[nr][nc] * weight
    return total


def find_density_peaks(state: GameState, top_n: int = 8) -> list:
    """
    Trouve les N meilleures zones de densité sur la carte (non occupées).
    Retourne une liste de (r, c, score_densité) triée par score décroissant.
    """
    scored = []
    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c):
                continue
            sector = get_sector(r, c)
            if state.is_danger(sector):
                continue
            score = density_score_area(state, r, c, radius=2)
            scored.append((r, c, score))
    scored.sort(key=lambda x: x[2], reverse=True)
    # Dédupliquer: garder les pics suffisamment espacés (distance > 3)
    peaks = []
    for r, c, score in scored:
        if all(hex_distance(r, c, pr, pc) > 3 for pr, pc, _ in peaks):
            peaks.append((r, c, score))
        if len(peaks) >= top_n:
            break
    return peaks


# ── Interactions multi-joueurs ─────────────────────────────────────────────

class EnemyProfile:
    """Profil d'un adversaire basé sur ses positions observées."""
    def __init__(self, player_id: int):
        self.player_id = player_id
        self.positions = []        # positions actuelles
        self.sector_counts = {}    # secteur → nombre de récolteuses
        self.total_count = 0
        self.dominant_sector = -1

    def update(self, positions: list, sector_counts: dict):
        self.positions = positions
        self.sector_counts = sector_counts
        self.total_count = sum(sector_counts.values())
        if sector_counts:
            self.dominant_sector = max(sector_counts, key=sector_counts.get)

    def density_center(self) -> tuple:
        """Centre de masse de ses récolteuses."""
        if not self.positions:
            return (ROWS // 2, COLS // 2)
        avg_r = sum(r for r, c in self.positions) / len(self.positions)
        avg_c = sum(c for r, c in self.positions) / len(self.positions)
        return (int(avg_r), int(avg_c))


def analyze_enemies(state: GameState) -> dict:
    """
    Analyse tous les adversaires présents sur la carte.
    Retourne {player_id: EnemyProfile}.
    """
    profiles = {}
    pid_str = str(state.player_id)

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

    # Remplir les profils
    for eid, profile in profiles.items():
        eid_str = str(eid)
        positions = [(r, c) for r in range(ROWS) for c in range(COLS)
                     if state.elements[r][c] == eid_str]
        sector_counts = {}
        for r, c in positions:
            s = get_sector(r, c)
            sector_counts[s] = sector_counts.get(s, 0) + 1
        profile.update(positions, sector_counts)

    return profiles


def shadow_value(state: GameState, r: int, c: int, enemy_profiles: dict) -> float:
    """
    Valeur de "shadow" d'une case: être adjacent à une récolteuse ennemie qui
    récolte une zone riche nous permet de partager sa production gratuitement.
    Les ennemis sur des zones denses valent la peine d'être suivis.
    """
    shadow_bonus = 0.0
    pid_str = str(state.player_id)
    for nr, nc in hex_neighbors(r, c):
        ch = state.elements[nr][nc]
        if ch in ('X', 'U') or ch == pid_str:
            continue
        # Case ennemie voisine: on partage sa production
        prod = cell_base_production(state, nr, nc)
        sharing = harvesters_sharing_cell(state, nr, nc)
        # Notre gain si on se met juste à côté
        shadow_bonus += prod / (sharing + 1) * 0.7  # 70% valeur (risque partage)
    return shadow_bonus


def blocker_value(state: GameState, r: int, c: int, enemy_profiles: dict) -> float:
    """
    Valeur de blocage: se placer entre un ennemi fort et une zone de haute densité
    l'empêche d'accéder à cette richesse.
    Calcule: est-ce que (r,c) coupe la route naturelle d'un ennemi?
    """
    if not enemy_profiles:
        return 0.0
    block_bonus = 0.0
    for eid, profile in enemy_profiles.items():
        if profile.total_count == 0:
            continue
        ec_r, ec_c = profile.density_center()
        # Est-ce que (r,c) est entre l'ennemi et une zone riche?
        # Chercher un pic de densité "derrière" notre position depuis l'ennemi
        local_density = density_score_area(state, r, c, radius=2)
        dist_to_enemy = hex_distance(r, c, ec_r, ec_c)
        if dist_to_enemy <= 4 and local_density > 12:  # zone riche à intercepter
            block_bonus += local_density * (4 - dist_to_enemy) * 0.5
    return block_bonus


def coexist_penalty(state: GameState, r: int, c: int) -> float:
    """
    Pénalité de co-existence: si on est dans un secteur déjà très peuplé
    d'ennemis, on va diluer tout le monde sans grand gain net.
    Retourne une pénalité (valeur négative ou nulle).
    """
    sector = get_sector(r, c)
    all_in_sector = state.count_harvesters_in_sector(sector)
    my_in_sector  = state.count_harvesters_in_sector(sector, state.player_id)
    enemy_in_sector = all_in_sector - my_in_sector

    if enemy_in_sector <= 0:
        return 0.0
    if all_in_sector >= 8:
        # Secteur très peuplé: la dilution annule presque tout
        return -30.0 * enemy_in_sector
    if enemy_in_sector >= 3:
        # Secteur ennemi fort: prudence
        return -10.0 * enemy_in_sector
    return 0.0


# ── Repositionnement dynamique ─────────────────────────────────────────────

def dynamic_relocation_target(state: GameState, r: int, c: int,
                               density_peaks: list,
                               enemy_profiles: dict) -> tuple | None:
    """
    Cible de déplacement dynamique pour une récolteuse.
    Combine:
    1. Gradient de densité (aller vers zones plus riches)
    2. Éloignement des ennemis en surnombre (éviter dilution)
    3. Opportunités de shadow sur ennemis en zones riches
    4. Blocage préventif des routes ennemies

    Retourne (nr, nc, score) ou None si rester sur place est optimal.
    """
    current_inc = harvester_income(state, r, c)
    best_dest = None
    best_score = current_inc * 1.2  # Seuil: 20% de gain minimum pour bouger

    for pr, pc, peak_density in density_peaks:
        if not state.is_free(pr, pc):
            continue
        sector = get_sector(pr, pc)
        if state.is_danger(sector):
            continue

        # Score de base = revenu marginal à la destination
        base = marginal_income(state, pr, pc)
        if base <= 0:
            continue

        # Bonus densité: la destination est-elle plus riche globalement?
        local_dens = density_score_area(state, pr, pc, radius=2)
        current_dens = density_score_area(state, r, c, radius=2)
        density_gain = (local_dens - current_dens) * 2.0

        # Bonus shadow: ennemis à suivre sur zones riches
        shd = shadow_value(state, pr, pc, enemy_profiles)

        # Bonus blocage
        blk = blocker_value(state, pr, pc, enemy_profiles)

        # Pénalité co-existence
        coex = coexist_penalty(state, pr, pc)

        total_score = base + density_gain + shd * 0.5 + blk * 0.3 + coex

        if total_score > best_score:
            best_score = total_score
            best_dest = (pr, pc, total_score)

    return best_dest


# ── Heatmap ────────────────────────────────────────────────────────────────

SECTOR_CENTERS = [
    (3, 4),   # secteur 0 (NW)
    (3, 13),  # secteur 1 (NE)
    (12, 4),  # secteur 2 (SW)
    (12, 13), # secteur 3 (SE)
]


def build_heatmap(state: GameState, turn: int, phase: str,
                  dangerous_sectors: set, condemned_sectors: set,
                  recently_safe: set = None, losing: bool = False,
                  enemy_profiles: dict = None,
                  density_peaks: list = None) -> list:
    """
    Heatmap des cases libres, triée par score décroissant.
    Intègre mouvement dynamique basé sur densité + tactiques multi-joueurs.
    """
    recently_safe  = recently_safe or set()
    enemy_profiles = enemy_profiles or {}
    density_peaks  = density_peaks or []

    all_factories = {(r, c) for r in range(ROWS) for c in range(COLS)
                     if state.elements[r][c] == 'U'}
    allies_per_sector = {s: state.count_harvesters_in_sector(s, state.player_id) for s in range(4)}

    # Pré-calculer les pics de densité si non fournis
    if not density_peaks:
        density_peaks = find_density_peaks(state, top_n=8)
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

            # ── Boost densité dynamique ───────────────────────────────
            local_density = density_score_area(state, r, c, radius=2)
            # Normaliser 0-1 (densité max théorique = 4×(1+6+12) = ~76)
            density_norm = local_density / 76.0
            score *= (1.0 + density_norm * 1.5)  # Jusqu'à ×2.5 pour zones très denses

            # Bonus si c'est un pic identifié
            if (r, c) in peak_set:
                score *= 1.4

            # ── Usine proche ──────────────────────────────────────────
            dist_to_factory = min((hex_distance(r, c, fr, fc) for fr, fc in all_factories), default=99)
            if dist_to_factory <= 2:
                score *= 1.5

            # ── Shadow sur ennemis en zones riches ────────────────────
            shd = shadow_value(state, r, c, enemy_profiles)
            score += shd

            # ── Blocage préventif des routes ennemies ─────────────────
            blk = blocker_value(state, r, c, enemy_profiles)
            score += blk * 0.4

            # ── Co-existence: éviter secteurs surpeuplés ──────────────
            coex = coexist_penalty(state, r, c)
            score += coex

            # ── Dispersion initiale (tour 1-2) ────────────────────────
            if turn <= 2:
                covered_sectors = {get_sector(hr, hc) for hr, hc in state.my_harvesters}
                if sector not in covered_sectors:
                    for sr, sc in SECTOR_CENTERS:
                        if get_sector(sr, sc) == sector:
                            dist_center = hex_distance(r, c, sr, sc)
                            if dist_center <= 3:
                                score *= 1.4
                            break

            # ── Retour post-ver ───────────────────────────────────────
            if sector in recently_safe:
                score *= 1.3

            # ── Retard au score: agressivité accrue ───────────────────
            if losing:
                enemy_in_sector = state.count_harvesters_in_sector(sector) - allies_per_sector[sector]
                if enemy_in_sector >= 2:
                    score *= 1.15

            # ── Anti-clustering ───────────────────────────────────────
            if allies_per_sector[sector] >= 5:
                score *= 0.5
            elif allies_per_sector[sector] >= 3:
                score *= 0.8

            # ── Pénalité voisins ennemis directs ──────────────────────
            enemy_neighbors = sum(1 for nr, nc in hex_neighbors(r, c)
                                  if state.elements[nr][nc] not in ('X', 'U')
                                  and state.elements[nr][nc] != str(state.player_id))
            if enemy_neighbors > 0:
                score -= enemy_neighbors * 10  # moins sévère: shadow peut valoir le coup

            result.append({'r': r, 'c': c, 'score': score, 'sector': sector,
                           'density': local_density})

    result.sort(key=lambda x: x['score'], reverse=True)
    return result


# ── Usines ─────────────────────────────────────────────────────────────────

def factory_roi(state: GameState, r: int, c: int, turns_left: int) -> float:
    """ROI d'une usine placée en (r,c) sur les tours restants."""
    if not state.is_free(r, c):
        return -1.0

    gain_per_turn = 0.0
    for ar, ac in cells_within_radius(r, c, 2):
        if (ar, ac) == (r, c):
            continue
        if state.elements[ar][ac] == 'U':
            continue
        if state.has_factory_in_radius(ar, ac, 2):
            continue

        sharing = harvesters_sharing_cell(state, ar, ac)
        if sharing > 0:
            gain_per_turn += (state.density[ar][ac] * 10.0) / sharing

    return gain_per_turn * turns_left - COST_FACTORY


def best_factory_position(state: GameState, turns_left: int):
    """Meilleure position pour une usine (ROI max)."""
    best_pos = None
    best_roi = 0.0

    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c):
                continue
            sector = get_sector(r, c)
            if state.is_danger(sector):
                continue
            roi = factory_roi(state, r, c, turns_left)
            if roi > best_roi:
                best_roi = roi
                best_pos = (r, c)

    return best_pos, best_roi


# ── Sabotage ───────────────────────────────────────────────────────────────

def sabotage_value(state: GameState, sector: int) -> float:
    """Valeur d'un sabotage: épice détruite chez les ennemis."""
    enemy_count = 0
    for r, c in state.harvesters_in_sector(sector):
        if state.elements[r][c] != str(state.player_id):
            enemy_count += 1

    my_count = state.count_harvesters_in_sector(sector, state.player_id)
    if my_count > 0:
        return -9999.0

    return enemy_count * COST_HARVESTER - COST_SABOTAGE


# ── Repositionnement dynamique ─────────────────────────────────────────────

def should_relocate(state: GameState, r: int, c: int,
                    threshold: float = 1.2,
                    density_peaks: list = None,
                    enemy_profiles: dict = None) -> tuple:
    """
    Détermine si une récolteuse devrait bouger.
    Utilise le repositionnement dynamique (gradient densité + multi-joueurs).
    Retourne (True, best_dest) ou (False, None).
    """
    density_peaks  = density_peaks or []
    enemy_profiles = enemy_profiles or {}

    current_income = harvester_income(state, r, c)

    # Revenu nul → déplacer immédiatement
    if current_income <= 0:
        best_pos = _find_best_free(state, exclude={(r, c)})
        return (True, best_pos) if best_pos else (False, None)

    dest = dynamic_relocation_target(
        state, r, c, density_peaks, enemy_profiles
    )
    if dest is not None:
        nr, nc, _ = dest
        return (True, (nr, nc))

    # Fallback: scan classique si dynamic ne trouve rien
    best_pos  = None
    best_gain = current_income * threshold

    for nr in range(ROWS):
        for nc in range(COLS):
            if not state.is_free(nr, nc):
                continue
            sector = get_sector(nr, nc)
            if state.is_danger(sector):
                continue
            val = marginal_income(state, nr, nc)
            if val > best_gain:
                best_gain = val
                best_pos  = (nr, nc)

    return (True, best_pos) if best_pos else (False, None)


def _find_best_free(state: GameState, avoid_sectors=None, exclude=None):
    avoid_sectors = avoid_sectors or set()
    exclude = exclude or set()
    best = None
    best_val = -1
    for r in range(ROWS):
        for c in range(COLS):
            if not state.is_free(r, c):
                continue
            if (r, c) in exclude:
                continue
            sector = get_sector(r, c)
            if sector in avoid_sectors or state.is_danger(sector):
                continue
            val = marginal_income(state, r, c)
            if val > best_val:
                best_val = val
                best = (r, c)
    return best


# ── Total income ───────────────────────────────────────────────────────────

def total_income(state: GameState) -> float:
    return sum(harvester_income(state, r, c) for r, c in state.my_harvesters)
