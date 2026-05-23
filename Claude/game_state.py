"""
Modèle de l'état du jeu For The Spice
Grille hexagonale 16x18 avec offset correct
"""

ROWS = 16
COLS = 18

SECTORS = {
    0: (range(0, 8),  range(0, 9)),   # nord-ouest
    1: (range(0, 8),  range(9, 18)),  # nord-est
    2: (range(8, 16), range(0, 9)),   # sud-ouest
    3: (range(8, 16), range(9, 18)),  # sud-est
}


def get_sector(row, col):
    if row <= 7:
        return 0 if col <= 8 else 1
    else:
        return 2 if col <= 8 else 3


def hex_neighbors(row, col):
    """Voisins hexagonaux corrects selon la parité de la ligne (offset grid)."""
    if row % 2 == 0:
        candidates = [
            (row-1, col-1), (row-1, col),
            (row,   col-1), (row,   col+1),
            (row+1, col-1), (row+1, col),
        ]
    else:
        candidates = [
            (row-1, col), (row-1, col+1),
            (row,   col-1), (row,   col+1),
            (row+1, col), (row+1, col+1),
        ]
    return [(r, c) for r, c in candidates if 0 <= r < ROWS and 0 <= c < COLS]


def hex_distance(r1, c1, r2, c2):
    """Distance hexagonale exacte via coordonnées cubiques."""
    # Conversion offset -> cube
    def to_cube(r, c):
        x = c - (r - (r & 1)) // 2
        z = r
        y = -x - z
        return x, y, z

    x1, y1, z1 = to_cube(r1, c1)
    x2, y2, z2 = to_cube(r2, c2)
    return max(abs(x1-x2), abs(y1-y2), abs(z1-z2))


def cells_within_radius(row, col, radius):
    """Toutes les cases dans un rayon hexagonal donné (BFS)."""
    visited = {(row, col)}
    frontier = {(row, col)}
    for _ in range(radius):
        next_f = set()
        for r, c in frontier:
            for nr, nc in hex_neighbors(r, c):
                if (nr, nc) not in visited:
                    visited.add((nr, nc))
                    next_f.add((nr, nc))
        frontier = next_f
    return visited


class GameState:
    def __init__(self, player_id):
        self.player_id = player_id
        self.turn = 0

        # Grille densité [row][col] -> 1-4
        self.density  = [[2] * COLS for _ in range(ROWS)]
        # Grille éléments [row][col] -> 'X','U','0'-'3'
        self.elements = [['X'] * COLS for _ in range(ROWS)]

        # Ornithoptères actifs: secteur -> tour de dernier déploiement
        self.orni_turn = {}

        # Avertissements vers: liste 4 éléments
        self.warnings = ['INCONNU'] * 4

        # Scores
        self.scores = {}

        # Cache positions
        self._my_harvesters = None
        self._my_factories  = None
        self._all_harvesters = None

    # ── Parsing ────────────────────────────────────────────────────────────

    def update_density(self, data):
        data = data.strip()
        if len(data) < ROWS * COLS:
            return
        idx = 0
        for r in range(ROWS):
            for c in range(COLS):
                ch = data[idx]
                self.density[r][c] = int(ch) if ch.isdigit() else 2
                idx += 1
        self._invalidate_cache()

    def update_elements(self, data):
        data = data.strip()
        if len(data) < ROWS * COLS:
            return
        idx = 0
        for r in range(ROWS):
            for c in range(COLS):
                self.elements[r][c] = data[idx]
                idx += 1
        self._invalidate_cache()

    def update_warnings(self, data):
        parts = data.strip().split('|')
        self.warnings = (parts + ['INCONNU'] * 4)[:4]

    def update_scores(self, data):
        for i, p in enumerate(data.strip().split('|')):
            try:
                self.scores[i] = int(p)
            except ValueError:
                pass

    def _invalidate_cache(self):
        self._my_harvesters  = None
        self._my_factories   = None
        self._all_harvesters = None

    # ── Accesseurs ─────────────────────────────────────────────────────────

    @property
    def my_harvesters(self):
        if self._my_harvesters is None:
            self._my_harvesters = {
                (r, c) for r in range(ROWS) for c in range(COLS)
                if self.elements[r][c] == str(self.player_id)
            }
        return self._my_harvesters

    @property
    def my_factories(self):
        if self._my_factories is None:
            self._my_factories = {
                (r, c) for r in range(ROWS) for c in range(COLS)
                if self.elements[r][c] == 'U'
            }
        return self._my_factories

    @property
    def all_harvesters(self):
        """Toutes les récolteuses (tous joueurs)."""
        if self._all_harvesters is None:
            self._all_harvesters = {
                (r, c) for r in range(ROWS) for c in range(COLS)
                if self.elements[r][c] not in ('X', 'U')
            }
        return self._all_harvesters

    @property
    def enemy_harvesters(self):
        pid = str(self.player_id)
        return {
            (r, c) for r in range(ROWS) for c in range(COLS)
            if self.elements[r][c] not in ('X', 'U') and self.elements[r][c] != pid
        }

    @property
    def enemy_factories(self):
        # Toutes les usines sont "neutres" visuellement mais on peut les
        # considérer comme ennemies si on veut bloquer autour
        return self.my_factories  # simplifié: toutes les usines connues

    def is_free(self, r, c):
        return 0 <= r < ROWS and 0 <= c < COLS and self.elements[r][c] == 'X'

    def my_score(self):
        return self.scores.get(self.player_id, 0)

    def is_danger(self, sector):
        return self.warnings[sector] == 'DANGER'

    def is_unknown(self, sector):
        return self.warnings[sector] == 'INCONNU'

    def has_factory_in_radius(self, r, c, radius=2):
        for nr, nc in cells_within_radius(r, c, radius):
            if self.elements[nr][nc] == 'U':
                return True
        return False

    def count_harvesters_in_sector(self, sector, player_id=None):
        rows_r, cols_r = SECTORS[sector]
        count = 0
        for r in rows_r:
            for c in cols_r:
                ch = self.elements[r][c]
                if player_id is None:
                    if ch not in ('X', 'U'):
                        count += 1
                else:
                    if ch == str(player_id):
                        count += 1
        return count

    def harvesters_in_sector(self, sector, player_id=None):
        rows_r, cols_r = SECTORS[sector]
        result = []
        for r in rows_r:
            for c in cols_r:
                ch = self.elements[r][c]
                if player_id is None:
                    if ch not in ('X', 'U'):
                        result.append((r, c))
                else:
                    if ch == str(player_id):
                        result.append((r, c))
        return result

    # ── Utilitaires locaux (mise à jour sans re-fetch) ─────────────────────

    def place_harvester(self, r, c):
        self.elements[r][c] = str(self.player_id)
        self._invalidate_cache()

    def place_factory(self, r, c):
        self.elements[r][c] = 'U'
        self._invalidate_cache()

    def move_harvester(self, r, c, nr, nc):
        self.elements[r][c] = 'X'
        self.elements[nr][nc] = str(self.player_id)
        self._invalidate_cache()
