# ============================================================
#  Maps.py  —  Utilitaires de carte pour RedHood
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
    Renvoie les 6 voisins hexagonaux de (x, y).
    Offset dépend de la parité de la ligne y :
      pair   : E(+1,0), O(-1,0), NE(0,-1), NO(-1,-1), SE(0,+1), SO(-1,+1)
      impair : E(+1,0), O(-1,0), NE(+1,-1), NO(0,-1), SE(+1,+1), SO(0,+1)
    """
    if y % 2 == 0:
        offsets = [(1, 0), (-1, 0), (0, -1), (-1, -1), (0, 1), (-1, 1)]
    else:
        offsets = [(1, 0), (-1, 0), (1, -1), (0, -1), (1, 1), (0, 1)]

    return [
        (x + dx, y + dy)
        for dx, dy in offsets
        if 0 <= x + dx < 18 and 0 <= y + dy < 16
    ]


def get_hex_neighbors_radius2(x, y):
    """
    Toutes les cases dans un rayon de 2 cases hex, sans la case centrale.
    """
    r1 = set(get_hex_neighbors(x, y))
    r2 = set()
    for vx, vy in r1:
        for nx, ny in get_hex_neighbors(vx, vy):
            r2.add((nx, ny))
    all_cells = r1 | r2
    all_cells.discard((x, y))
    return all_cells


# --------------- Utilitaires généraux ----------------------

def get_secteur_de_case(x, y):
    """Numéro de secteur (0-3) pour la case (col x, ligne y)."""
    if y < 8 and x < 9:  return 0
    if y < 8 and x >= 9: return 1
    if y >= 8 and x < 9: return 2
    return 3


def get_secteur(choix_matrice, num, maps):
    """Sous-matrice d'un secteur donné. choix_matrice : 'obj' ou 'dns'."""
    carte = maps[choix_matrice]
    limites = {
        0: (0, 8, 0, 9), 1: (0, 8, 9, 18),
        2: (8, 16, 0, 9), 3: (8, 16, 9, 18)
    }
    if num not in limites:
        raise ValueError("Secteur doit être 0-3.")
    r0, r1, c0, c1 = limites[num]
    return [ligne[c0:c1] for ligne in carte[r0:r1]]


def update_map(type_commande, donnees_serveur, maps):
    """
    Met à jour 'obj' (ELEMENTS) ou 'dns' (DENSITE) depuis la chaîne de 288 chars.
    """
    if len(donnees_serveur) != 288:
        print(f"[update_map] {len(donnees_serveur)} chars reçus, attendu 288.")
        return maps
    cle = {'DENSITE': 'dns', 'ELEMENTS': 'obj'}.get(type_commande)
    if cle is None:
        print(f"[update_map] Commande inconnue : {type_commande}")
        return maps
    carte = maps[cle]
    for y in range(16):
        for x in range(18):
            carte[y][x] = donnees_serveur[y * 18 + x]
    return maps


def get_my_spice(reponse_scores, mon_id):
    """Extrait notre stock depuis la réponse SCORES."""
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


# --------------- Densité effective -------------------------

def apply_bonus_factories(maps):
    """
    Retourne une matrice 16x18 d'entiers = densité effective après bonus usines.
    - Case usine → 0 production
    - Cases dans rayon 2 d'une usine → ×2 (non cumulable)
    Ne modifie PAS maps['dns'].
    """
    carte_obj = maps['obj']
    carte_dns = maps['dns']

    dns_eff = [[int(carte_dns[y][x]) for x in range(18)] for y in range(16)]

    cases_boostees = set()
    for y in range(16):
        for x in range(18):
            if carte_obj[y][x] == 'U':
                dns_eff[y][x] = 0
                for nx, ny in get_hex_neighbors_radius2(x, y):
                    if carte_obj[ny][nx] != 'U':
                        cases_boostees.add((nx, ny))

    for bx, by in cases_boostees:
        dns_eff[by][bx] *= 2

    return dns_eff


# --------------- Placement récolteuses ---------------------

def find_best_locations(maps, mon_id, top_n=20, cases_deja_choisies=None):
    """
    Trouve les meilleures cases libres pour une récolteuse.

    Score d'une case = rendement_brut_zone - malus_allies_dans_zone
      - rendement_brut_zone : somme des densités effectives de la case + ses 6 voisins
        (les cases occupées par une usine comptent 0, celles avec une récolteuse
        ennemie comptent à moitié car on partage)
      - malus_allies_dans_zone : pour chaque récolteuse alliée déjà dans la zone
        (case + 6 voisins), on retire 'rendement_brut / (nb_allies_zone + 1)' car
        la production sera divisée → pénalise fortement le clustering

    cases_deja_choisies : set de (x,y) déjà réservées ce tour (évite les doublons
                          quand on choisit plusieurs spots d'un coup)

    Retourne :
      {
        "top_spots": [{"coords":(x,y), "score":int, "rendement":int, "secteur":int}],
        "classement_secteurs": [...]
      }
    """
    carte_obj = maps['obj']
    dns_eff   = apply_bonus_factories(maps)
    exclues   = cases_deja_choisies or set()

    emplacements = []
    for y in range(16):
        for x in range(18):
            if carte_obj[y][x] != 'X':
                continue
            if (x, y) in exclues:
                continue

            zone = [(x, y)] + get_hex_neighbors(x, y)

            rendement_brut = 0
            allies_zone    = 0
            for vx, vy in zone:
                elem = carte_obj[vy][vx]
                if elem == 'U':
                    continue  # usine = 0 production
                d = dns_eff[vy][vx]
                if elem == str(mon_id):
                    allies_zone += 1
                    rendement_brut += d
                elif elem.isdigit():
                    rendement_brut += d // 2  # on partage avec l'ennemi
                else:
                    rendement_brut += d

            # Malus clustering : si on pose ici, la production des cases
            # déjà couvertes par des alliés sera divisée entre (allies+1) récolteuses
            # On retire la part que perdront nos alliés existants.
            if allies_zone > 0:
                # Densité des cases partagées entre nos alliés et la nouvelle récolteuse
                shared_prod = sum(
                    dns_eff[vy][vx]
                    for vx, vy in zone
                    if carte_obj[vy][vx] == str(mon_id)
                )
                # Perte nette = ce que nos alliés perdent en partageant
                malus = shared_prod * allies_zone / (allies_zone + 1)
            else:
                malus = 0

            score_final = rendement_brut - malus

            emplacements.append({
                "coords":   (x, y),
                "score":    score_final,
                "rendement": rendement_brut,
                "secteur":  get_secteur_de_case(x, y)
            })

    emplacements.sort(key=lambda i: i['score'], reverse=True)
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


# --------------- Placement usines --------------------------

def find_best_factory_spot(maps, mon_id, usines_deja_choisies=None):
    """
    Cherche la meilleure case libre pour une usine.

    Score = (allies_dans_rayon2 × rendement_moyen_allies) - (ennemis_dans_rayon2 × penalite)

    Conditions minimales :
      - Case libre ('X')
      - Au moins 1 récolteuse alliée dans le rayon 2  (assoupli depuis 2)
      - Pas d'usine dans le rayon 2 (pas de double-couverture inutile)

    usines_deja_choisies : set de (x,y) déjà réservées ce tour
    """
    carte_obj    = maps['obj']
    dns_eff      = apply_bonus_factories(maps)
    exclues      = usines_deja_choisies or set()

    meilleur_spot  = None
    meilleur_score = -9999

    for y in range(16):
        for x in range(18):
            if carte_obj[y][x] != 'X':
                continue
            if (x, y) in exclues:
                continue

            zone = get_hex_neighbors_radius2(x, y)

            # Pas d'usine déjà dans la zone
            if any(carte_obj[vy][vx] == 'U' for vx, vy in zone):
                continue

            allies  = 0
            ennemis = 0
            gain_allies = 0  # épice supplémentaire générée pour nous (doublement)

            for vx, vy in zone:
                elem = carte_obj[vy][vx]
                if elem == str(mon_id):
                    allies += 1
                    gain_allies += dns_eff[vy][vx]  # on double cette production
                elif elem.isdigit():
                    ennemis += 1

            # Seuil minimal : au moins 1 allié bénéficiaire
            if allies < 1:
                continue

            # Bonus : plus il y a d'alliés, mieux c'est
            # Malus : chaque ennemi boosté gratuitement coûte cher
            score = gain_allies + (allies * 5) - (ennemis * 20)

            if score > meilleur_score:
                meilleur_score = score
                meilleur_spot  = (x, y)

    return {"coords": meilleur_spot, "score_rentabilite": meilleur_score}


# --------------- Sabotage ----------------------------------

def strategic_sabotage_advance(maps, mon_id, classement_ennemis):
    """
    Identifie le meilleur secteur à saboter.
    Cible le leader en priorité. Calcule gains vs pertes.
    Retourne liste de candidats triés par score décroissant.
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
        # Refuser si on perdrait TOUTES nos récolteuses
        if s['allies'] > 0 and s['allies'] == total_allies:
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


# --------------- Évacuation --------------------------------

def evacuation_protocol(maps, mon_id, alertes_secteurs):
    """
    Trouve des ordres de déplacement pour les récolteuses en DANGER.
    Retourne [{"orig_x", "orig_y", "dest_x", "dest_y"}, ...]
    """
    carte_obj = maps['obj']

    secteurs_dangereux = {i for i in range(4) if alertes_secteurs[i] == 'DANGER'}
    if not secteurs_dangereux:
        return []

    en_danger = [
        (x, y)
        for y in range(16) for x in range(18)
        if carte_obj[y][x] == str(mon_id)
        and get_secteur_de_case(x, y) in secteurs_dangereux
    ]
    if not en_danger:
        return []

    # Spots sûrs triés par score (anti-clustering inclus)
    spots_surs = [
        s for s in find_best_locations(maps, mon_id, top_n=50)["top_spots"]
        if s["secteur"] not in secteurs_dangereux
    ]

    ordres        = []
    spots_utilises = set()
    for ox, oy in en_danger:
        for spot in spots_surs:
            coords = spot["coords"]
            if coords not in spots_utilises:
                ordres.append({
                    "orig_x": ox, "orig_y": oy,
                    "dest_x": coords[0], "dest_y": coords[1]
                })
                spots_utilises.add(coords)
                break

    return ordres