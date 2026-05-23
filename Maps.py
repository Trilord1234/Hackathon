# ============================================================
#  Maps.py  —  Utilitaires de carte pour For The Spice
# ============================================================

# --------------- Structures de données initiales -----------

maps_obj = [['X'] * 18 for _ in range(16)]
maps_dns = [['1'] * 18 for _ in range(16)]

maps = {
    'obj': maps_obj,
    'dns': maps_dns
}

# --------------- Voisinage hexagonal -----------------------

def get_hex_neighbors(x, y):
    """
    Renvoie les coordonnées (col, ligne) des 6 voisins hexagonaux de (x, y).
    
    La grille utilise un décalage basé sur la parité de la LIGNE (y) :
      - Si y est pair  : les voisins diagonaux sont à  (x-1) à gauche
      - Si y est impair: les voisins diagonaux sont à  (x+1) à droite
    
    Offsets (dx, dy) pour les 6 directions hex :
      pair  : E(+1,0), O(-1,0), NE(0,-1), NO(-1,-1), SE(0,+1), SO(-1,+1)
      impair: E(+1,0), O(-1,0), NE(+1,-1), NO(0,-1),  SE(+1,+1), SO(0,+1)
    """
    if y % 2 == 0:
        offsets = [(1, 0), (-1, 0), (0, -1), (-1, -1), (0, 1), (-1, 1)]
    else:
        offsets = [(1, 0), (-1, 0), (1, -1), (0, -1),  (1, 1),  (0, 1)]

    neighbors = []
    for dx, dy in offsets:
        nx, ny = x + dx, y + dy
        if 0 <= nx < 18 and 0 <= ny < 16:
            neighbors.append((nx, ny))
    return neighbors


def get_hex_neighbors_radius2(x, y):
    """
    Renvoie toutes les cases dans un rayon de 2 cases (hex) autour de (x, y),
    sans inclure (x, y) lui-même.
    """
    r1 = set(get_hex_neighbors(x, y))
    r2 = set()
    for vx, vy in r1:
        for nx, ny in get_hex_neighbors(vx, vy):
            r2.add((nx, ny))
    # Union des deux rayons, sans la case centrale
    all_cells = r1 | r2
    all_cells.discard((x, y))
    return all_cells


# --------------- Fonctions utilitaires ---------------------

def get_secteur(choix_matrice, num, maps):
    """
    Renvoie la sous-matrice (liste de listes) d'un secteur donné.

    choix_matrice : 'obj' ou 'dns'
    num           : 0, 1, 2 ou 3
    maps          : dict {'obj': ..., 'dns': ...}
    """
    carte_active = maps[choix_matrice]

    limites_secteurs = {
        0: (0, 8, 0, 9),   # lignes 0-7,  colonnes 0-8
        1: (0, 8, 9, 18),  # lignes 0-7,  colonnes 9-17
        2: (8, 16, 0, 9),  # lignes 8-15, colonnes 0-8
        3: (8, 16, 9, 18)  # lignes 8-15, colonnes 9-17
    }

    if num not in limites_secteurs:
        raise ValueError("Le numéro du secteur doit être 0, 1, 2 ou 3.")

    r_min, r_max, c_min, c_max = limites_secteurs[num]
    return [ligne[c_min:c_max] for ligne in carte_active[r_min:r_max]]


def get_secteur_de_case(x, y):
    """Retourne le numéro de secteur (0-3) pour une case (col x, ligne y)."""
    if y < 8 and x < 9:   return 0
    if y < 8 and x >= 9:  return 1
    if y >= 8 and x < 9:  return 2
    return 3


def update_map(type_commande, donnees_serveur, maps):
    """
    Met à jour la carte 'obj' ou 'dns' à partir de la chaîne de 288 caractères
    renvoyée par le serveur.

    type_commande  : 'DENSITE' ou 'ELEMENTS'
    donnees_serveur: string de 288 caractères
    maps           : dict {'obj': ..., 'dns': ...}
    """
    if len(donnees_serveur) != 288:
        print(f"[update_map] Erreur : {len(donnees_serveur)} caractères reçus (attendu 288).")
        return maps

    cle = {'DENSITE': 'dns', 'ELEMENTS': 'obj'}.get(type_commande)
    if cle is None:
        print(f"[update_map] Type de commande inconnu : {type_commande}")
        return maps

    carte = maps[cle]
    for y in range(16):
        for x in range(18):
            carte[y][x] = donnees_serveur[y * 18 + x]
    return maps


def get_my_spice(reponse_scores, mon_id):
    """
    Extrait le stock d'épice du joueur mon_id depuis la réponse SCORES.
    reponse_scores : ex. "995000|1002000|980000|990000"
    """
    return int(reponse_scores.split('|')[int(mon_id)])


def classify_threats_scores(reponse_scores, mon_id):
    """
    Retourne la liste des adversaires triée par score décroissant.
    [{"id_joueur": "2", "score": 1002000}, ...]
    """
    ennemis = []
    for idx, val in enumerate(reponse_scores.split('|')):
        if val.strip() and str(idx) != str(mon_id):
            ennemis.append({"id_joueur": str(idx), "score": int(val)})
    ennemis.sort(key=lambda e: e["score"], reverse=True)
    return ennemis


# --------------- Analyse de la carte -----------------------

def apply_bonus_factories(maps):
    """
    Calcule la carte de densité *effective* en tenant compte des usines.
    - Une case usine produit 0 épice.
    - Une usine double la densité des cases dans un rayon de 2 (bonus non cumulable).
    
    IMPORTANT : ne modifie PAS maps['dns'] en place — retourne une nouvelle
    matrice dns_effective pour ne pas corrompre les données brutes du serveur.
    """
    carte_obj = maps['obj']
    carte_dns = maps['dns']

    # Copie de travail (valeurs entières)
    dns_eff = [[int(carte_dns[y][x]) for x in range(18)] for y in range(16)]

    # Marquer les cases à booster (union des rayons 2 de toutes les usines)
    cases_boostees = set()
    for y in range(16):
        for x in range(18):
            if carte_obj[y][x] == 'U':
                dns_eff[y][x] = 0  # la case usine elle-même ne produit rien
                for nx, ny in get_hex_neighbors_radius2(x, y):
                    if carte_obj[ny][nx] != 'U':
                        cases_boostees.add((nx, ny))

    for bx, by in cases_boostees:
        dns_eff[by][bx] *= 2  # bonus x2, non cumulable (set = une seule fois par case)

    return dns_eff  # matrice 16x18 d'entiers


def find_best_locations(maps, top_n=10):
    """
    Trouve les meilleures cases libres où placer une récolteuse.
    Utilise la densité effective (bonus usines inclus).

    Retourne :
      {
        "top_spots":          [{"coords": (x,y), "rendement": int, "secteur": int}, ...],
        "classement_secteurs": [{"secteur": int, "nombre_de_spots": int, "score_cumule": int}, ...]
      }
    """
    carte_obj = maps['obj']
    dns_eff   = apply_bonus_factories(maps)  # matrice entière avec bonus

    emplacements = []
    for y in range(16):
        for x in range(18):
            if carte_obj[y][x] != 'X':
                continue

            # Case centrale + 6 voisins hex
            zone = [(x, y)] + get_hex_neighbors(x, y)
            rendement = 0
            for vx, vy in zone:
                # Ne pas compter les cases usines dans le rendement
                if carte_obj[vy][vx] != 'U':
                    rendement += dns_eff[vy][vx]

            emplacements.append({
                "coords":   (x, y),
                "rendement": rendement,
                "secteur":  get_secteur_de_case(x, y)
            })

    emplacements.sort(key=lambda i: i['rendement'], reverse=True)
    top = emplacements[:top_n]

    stats = {i: {"count": 0, "score_total": 0} for i in range(4)}
    for p in top:
        stats[p["secteur"]]["count"]       += 1
        stats[p["secteur"]]["score_total"] += p["rendement"]

    classement = sorted(
        [{"secteur": s, "nombre_de_spots": v["count"], "score_cumule": v["score_total"]}
         for s, v in stats.items()],
        key=lambda s: (s["nombre_de_spots"], s["score_cumule"]),
        reverse=True
    )

    return {"top_spots": top, "classement_secteurs": classement}


def analyze_competition_spice(x, y, maps, mon_id):
    """
    Analyse une case : qui récolte dessus, quelle est sa densité effective ?

    Retourne :
      {
        "case_epice":          (x, y),
        "densite_epice":       int (densité effective),
        "recolteuses_alliees": [(x,y), ...],
        "recolteuses_adverses":[{"coords": (x,y), "id_joueur": str}, ...],
        "usine_sur_case":      bool,
        "diviseur_recolte":    int  (nombre total de récolteuses sur la case/voisins)
      }
    """
    carte_obj = maps['obj']
    dns_eff   = apply_bonus_factories(maps)

    zone = [(x, y)] + get_hex_neighbors(x, y)

    resultat = {
        "case_epice":           (x, y),
        "densite_epice":        dns_eff[y][x],
        "recolteuses_alliees":  [],
        "recolteuses_adverses": [],
        "usine_sur_case":       carte_obj[y][x] == 'U',
        "diviseur_recolte":     0
    }

    for vx, vy in zone:
        elem = carte_obj[vy][vx]
        if elem.isdigit():
            resultat["diviseur_recolte"] += 1
            if elem == str(mon_id):
                resultat["recolteuses_alliees"].append((vx, vy))
            else:
                resultat["recolteuses_adverses"].append({"coords": (vx, vy), "id_joueur": elem})

    return resultat


def find_best_factory_spot(maps, mon_id):
    """
    Cherche la meilleure case libre pour poser une usine.
    Score = (nb alliés boostés × 10) + (épice potentielle alliée) − (nb ennemis boostés × 15)
    
    Conditions :
      - La case doit être libre ('X')
      - Au moins 2 récolteuses alliées dans le rayon 2
      - Pas d'usine déjà présente dans le rayon 2 (évite les doublons inutiles)
    """
    carte_obj = maps['obj']
    dns_eff   = apply_bonus_factories(maps)

    meilleur_spot  = None
    meilleur_score = -9999

    for y in range(16):
        for x in range(18):
            if carte_obj[y][x] != 'X':
                continue

            zone = get_hex_neighbors_radius2(x, y)

            # Refuser si une usine est déjà dans la zone (bonus déjà couvert)
            if any(carte_obj[vy][vx] == 'U' for vx, vy in zone):
                continue

            allies  = 0
            ennemis = 0
            epice   = 0
            for vx, vy in zone:
                elem = carte_obj[vy][vx]
                if elem == str(mon_id):
                    allies += 1
                    epice  += dns_eff[vy][vx]
                elif elem.isdigit():
                    ennemis += 1

            if allies < 2:
                continue

            score = (allies * 10) + epice - (ennemis * 15)
            if score > meilleur_score:
                meilleur_score = score
                meilleur_spot  = (x, y)

    return {"coords": meilleur_spot, "score_rentabilite": meilleur_score}


def strategic_sabotage_advance(maps, mon_id, classement_ennemis):
    """
    Identifie le meilleur secteur à saboter.
    Cible prioritairement le leader. Refuse les secteurs où seuls nos alliés sont présents.
    Score = gains (ennemis détruits, ×3 si leader) − pertes (nos récolteuses sacrifiées).

    Retourne une liste de candidats triés par score décroissant.
    """
    carte_obj = maps['obj']
    if not classement_ennemis:
        return []

    leader_id = classement_ennemis[0]["id_joueur"]
    stats = {i: {'ennemis': 0, 'allies': 0, 'leader': 0} for i in range(4)}
    total_allies = 0

    for y in range(16):
        for x in range(18):
            elem = carte_obj[y][x]
            if not elem.isdigit():
                continue
            sec = get_secteur_de_case(x, y)
            if elem == str(mon_id):
                stats[sec]['allies'] += 1
                total_allies += 1
            else:
                stats[sec]['ennemis'] += 1
                if elem == leader_id:
                    stats[sec]['leader'] += 1

    cibles = []
    for sec, s in stats.items():
        if s['ennemis'] == 0:
            continue
        # Ne pas saboter un secteur où seuls nos alliés seraient touchés
        if s['allies'] > 0 and total_allies > 0 and s['allies'] == total_allies:
            continue

        gains  = (s['ennemis'] - s['leader']) * 1 + s['leader'] * 3
        pertes = s['allies'] * (10 / max(total_allies, 1))
        score  = gains - pertes

        if score > 0:
            cibles.append({
                "secteur":          sec,
                "score_cible":      score,
                "ennemis_detruits": s['ennemis'],
                "dont_leader":      s['leader'],
                "sacrifices":       s['allies']
            })

    cibles.sort(key=lambda c: c['score_cible'], reverse=True)
    return cibles


def evacuation_protocol(maps, mon_id, alertes_secteurs):
    """
    Identifie les récolteuses en DANGER et leur trouve un spot de repli sûr.

    alertes_secteurs : liste de 4 strings, ex ['CALME', 'DANGER', 'INCONNU', 'CALME']

    Retourne une liste d'ordres :
      [{"orig_x": int, "orig_y": int, "dest_x": int, "dest_y": int}, ...]
    """
    carte_obj = maps['obj']

    secteurs_dangereux = {i for i in range(4) if alertes_secteurs[i] == 'DANGER'}
    if not secteurs_dangereux:
        return []

    en_danger = [
        (x, y)
        for y in range(16)
        for x in range(18)
        if carte_obj[y][x] == str(mon_id) and get_secteur_de_case(x, y) in secteurs_dangereux
    ]
    if not en_danger:
        return []

    # Spots de repli : cases libres dans des secteurs non dangereux, triées par rendement
    spots_dispos = [
        s for s in find_best_locations(maps, top_n=50)["top_spots"]
        if s["secteur"] not in secteurs_dangereux
    ]

    ordres = []
    spots_utilises = set()
    for (ox, oy) in en_danger:
        for spot in spots_dispos:
            coords = spot["coords"]
            if coords not in spots_utilises:
                ordres.append({
                    "orig_x": ox, "orig_y": oy,
                    "dest_x": coords[0], "dest_y": coords[1]
                })
                spots_utilises.add(coords)
                break

    return ordres