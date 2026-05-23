"""
Moteur stratégique For The Spice
- Valeur marginale réelle (partage hexagonal)
- Heatmap avec tactiques avancées
- ROI usines et récolteuses
- Évaluation des menaces
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
    # La case elle-même si récolteuse
    if state.elements[r][c] not in ('X', 'U'):
        count += 1
    # Les voisins qui sont des récolteuses
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
        after  = before + 1  # on ajoute notre récolteuse

        # Notre gain sur cette case
        gain += prod / after

        if before > 0:
            dilution = prod / before - prod / after
            # Perte pour la récolteuse alliée SUR cette case (elle se dilue aussi)
            if state.elements[hr][hc] == str(state.player_id):
                gain -= dilution
            # Perte pour les récolteuses alliées VOISINES de cette case
            for nr, nc in hex_neighbors(hr, hc):
                if state.elements[nr][nc] == str(state.player_id) and (nr, nc) != (r, c):
                    gain -= dilution

    return gain


# ── Heatmap ────────────────────────────────────────────────────────────────

def build_heatmap(state: GameState, turn: int, phase: str,
                  dangerous_sectors: set, condemned_sectors: set) -> list:
    """
    Construit la heatmap des cases libres, triée par score décroissant.
    Intègre:
    - Valeur marginale réelle
    - Bonus si proche d'une usine (boost déjà en place)
    - Bonus si près d'une usine ennemie (blocus industriel)
    - Pénalité anti-clustering (trop de récolteuses dans le secteur)
    - Pénalité de voisinage ennemi direct
    - Exclusion des secteurs dangereux/condamnés
    """
    enemies = state.enemy_harvesters
    factories = state.my_factories
    all_factories = {(r, c) for r in range(ROWS) for c in range(COLS)
                     if state.elements[r][c] == 'U'}

    allies_per_sector = {s: state.count_harvesters_in_sector(s, state.player_id) for s in range(4)}
    enemy_per_sector  = {s: state.count_harvesters_in_sector(s) - allies_per_sector[s] for s in range(4)}

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

            # Bonus: proche d'une usine déjà posée (boost garanti)
            dist_to_factory = min((hex_distance(r, c, fr, fc) for fr, fc in all_factories), default=99)
            if dist_to_factory <= 2:
                score *= 1.5

            # Bonus pression: se placer dans la zone de récolteuses ennemies
            if any(hex_distance(r, c, er, ec) <= 2 for er, ec in enemies):
                score *= 1.2

            # Pénalité anti-clustering: trop de nos récolteuses dans ce secteur
            if allies_per_sector[sector] >= 5:
                score *= 0.5
            elif allies_per_sector[sector] >= 3:
                score *= 0.8

            # Pénalité voisinage ennemi direct (risque de partage)
            enemy_neighbors = sum(1 for nr, nc in hex_neighbors(r, c)
                                  if state.elements[nr][nc] not in ('X', 'U')
                                  and state.elements[nr][nc] != str(state.player_id))
            if enemy_neighbors > 0:
                score -= enemy_neighbors * 15

            result.append({'r': r, 'c': c, 'score': score, 'sector': sector})

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
            continue  # Déjà boosté, pas de gain marginal

        # Toutes les récolteuses qui récoltent cette case bénéficient du bonus
        sharing = harvesters_sharing_cell(state, ar, ac)
        if sharing > 0:
            gain_per_turn += (state.density[ar][ac] * 10.0) / sharing

    return gain_per_turn * turns_left - COST_FACTORY


def best_factory_position(state: GameState, turns_left: int):
    """Meilleure position pour une usine (ROI max)."""
    best_pos = None
    best_roi = 0.0  # On veut un ROI positif

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
    """
    Valeur d'un sabotage sur le secteur:
    = épice détruite chez les ennemis (récolteuses perdues × coût moyen)
    """
    enemy_count = 0
    for r, c in state.harvesters_in_sector(sector):
        if state.elements[r][c] != str(state.player_id):
            enemy_count += 1

    my_count = state.count_harvesters_in_sector(sector, state.player_id)
    # Ne saboter que si peu/pas de nos unités dans le secteur
    if my_count > 0:
        return -9999.0

    # Valeur: chaque récolteuse ennemie détruite = COST_HARVESTER d'avantage
    return enemy_count * COST_HARVESTER - COST_SABOTAGE


# ── Repositionnement ───────────────────────────────────────────────────────

def should_relocate(state: GameState, r: int, c: int, threshold=1.35) -> tuple:
    """
    Détermine si une récolteuse devrait bouger.
    Retourne (True, best_dest) ou (False, None).
    """
    current_income = harvester_income(state, r, c)
    if current_income <= 0:
        # Toujours déplacer si revenu nul
        best_pos = _find_best_free(state, exclude={(r, c)})
        return (True, best_pos) if best_pos else (False, None)

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
