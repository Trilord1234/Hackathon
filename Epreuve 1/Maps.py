# ============================================================
#  Maps.py  —  Utilitaires de carte pour RedHood (v2)
# ============================================================

maps_obj = [['X'] * 18 for _ in range(16)]
maps_dns = [['1'] * 18 for _ in range(16)]
maps = {'obj': maps_obj, 'dns': maps_dns}

ROWS, COLS = 16, 18

# ── Voisinage hexagonal ─────────────────────────────────────

def get_hex_neighbors(x, y):
    """6 voisins hexagonaux de (col x, ligne y). Offset pair/impair sur y."""
    if y % 2 == 0:
        offsets = [(1,0),(-1,0),(0,-1),(-1,-1),(0,1),(-1,1)]
    else:
        offsets = [(1,0),(-1,0),(1,-1),(0,-1),(1,1),(0,1)]
    return [(x+dx, y+dy) for dx,dy in offsets
            if 0 <= x+dx < COLS and 0 <= y+dy < ROWS]

def get_hex_neighbors_radius2(x, y):
    """Toutes les cases à distance ≤ 2 (hex), sans la case centrale."""
    r1 = set(get_hex_neighbors(x, y))
    r2 = set()
    for vx, vy in r1:
        for nx, ny in get_hex_neighbors(vx, vy):
            r2.add((nx, ny))
    all_cells = r1 | r2
    all_cells.discard((x, y))
    return all_cells

# ── Utilitaires généraux ────────────────────────────────────

def get_secteur_de_case(x, y):
    if y < 8 and x < 9:  return 0
    if y < 8 and x >= 9: return 1
    if y >= 8 and x < 9: return 2
    return 3

def get_secteur(choix_matrice, num, maps):
    carte = maps[choix_matrice]
    limites = {0:(0,8,0,9),1:(0,8,9,18),2:(8,16,0,9),3:(8,16,9,18)}
    if num not in limites: raise ValueError("Secteur 0-3.")
    r0,r1,c0,c1 = limites[num]
    return [ligne[c0:c1] for ligne in carte[r0:r1]]

def update_map(type_commande, donnees_serveur, maps):
    """Met à jour 'obj' (ELEMENTS) ou 'dns' (DENSITE)."""
    if len(donnees_serveur) != 288:
        print(f"[update_map] {len(donnees_serveur)} chars, attendu 288.")
        return maps
    cle = {'DENSITE':'dns','ELEMENTS':'obj'}.get(type_commande)
    if cle is None:
        print(f"[update_map] Commande inconnue : {type_commande}"); return maps
    carte = maps[cle]
    for y in range(ROWS):
        for x in range(COLS):
            carte[y][x] = donnees_serveur[y * COLS + x]
    return maps

def get_my_spice(reponse_scores, mon_id):
    return int(reponse_scores.split('|')[int(mon_id)])

def classify_threats_scores(reponse_scores, mon_id):
    ennemis = []
    for idx, val in enumerate(reponse_scores.split('|')):
        if val.strip() and str(idx) != str(mon_id):
            ennemis.append({"id_joueur": str(idx), "score": int(val)})
    ennemis.sort(key=lambda e: e["score"], reverse=True)
    return ennemis

# ── Densité effective (avec bonus usines) ───────────────────

def apply_bonus_factories(maps):
    """
    Retourne matrice 16×18 d'entiers = densité effective.
    Case usine → 0. Cases dans rayon 2 d'une usine → ×2 (non cumulable).
    Ne modifie pas maps['dns'].
    """
    carte_obj = maps['obj']
    carte_dns = maps['dns']
    dns_eff = [[int(carte_dns[y][x]) for x in range(COLS)] for y in range(ROWS)]
    cases_boostees = set()
    for y in range(ROWS):
        for x in range(COLS):
            if carte_obj[y][x] == 'U':
                dns_eff[y][x] = 0
                for nx,ny in get_hex_neighbors_radius2(x, y):
                    if carte_obj[ny][nx] != 'U':
                        cases_boostees.add((nx,ny))
    for bx,by in cases_boostees:
        dns_eff[by][bx] *= 2
    return dns_eff

# ── Rendement ACTUEL d'une récolteuse déjà placée ──────────
# BUGFIX v2 : cette fonction calcule ce que notre récolteuse en (x,y)
# GAGNE RÉELLEMENT chaque tour (sans ajouter de +1 fictif).

def rendement_actuel(x, y, maps, mon_id, dns_eff):
    """
    Épice récoltée par tour par notre récolteuse déjà en place en (x, y).
    La récolteuse EXISTE déjà sur la carte — on ne simule pas d'ajout.
    """
    carte_obj = maps['obj']
    zone = [(x, y)] + get_hex_neighbors(x, y)
    total = 0.0
    for vx, vy in zone:
        if carte_obj[vy][vx] == 'U':
            continue
        d = dns_eff[vy][vx]
        # Nombre de récolteuses (tous joueurs) couvrant (vx,vy)
        n = sum(
            1 for rx, ry in get_hex_neighbors(vx, vy) + [(vx, vy)]
            if carte_obj[ry][rx].isdigit()
        )
        if n > 0:
            total += d / n
    return total

# ── Gain NET si on AJOUTE une récolteuse en (x,y) ──────────

def gain_placement(x, y, maps, mon_id, dns_eff):
    """
    Gain net si on AJOUTE une récolteuse en (x,y).
    = épice gagnée par notre nouvelle récolteuse
      - épice perdue par nos alliés qui se font diluer.
    (x,y) doit être libre ('X') avant l'appel.
    """
    carte_obj = maps['obj']
    zone = [(x, y)] + get_hex_neighbors(x, y)
    notre_gain  = 0.0
    perte_allies = 0.0

    for vx, vy in zone:
        if carte_obj[vy][vx] == 'U':
            continue
        d = dns_eff[vy][vx]
        recolteurs = [
            (rx, ry) for rx, ry in [(vx, vy)] + get_hex_neighbors(vx, vy)
            if carte_obj[ry][rx].isdigit()
        ]
        n = len(recolteurs)
        # Notre nouvelle récolteuse reçoit d/(n+1)
        notre_gain += d / (n + 1)
        # Chaque allié perd d/n - d/(n+1)
        allies_ici = [r for r in recolteurs if carte_obj[r[1]][r[0]] == str(mon_id)]
        if n > 0 and allies_ici:
            perte_par_allie = d / n - d / (n + 1)
            perte_allies   += perte_par_allie * len(allies_ici)

    return notre_gain - perte_allies

# ── Gain NET si on DÉPLACE notre récolteuse de orig → dest ──
# BUGFIX v2 : utilise rendement_actuel pour l'origine (sans +1 fictif).

def gain_deplacement(ox, oy, dx, dy, maps, mon_id, dns_eff):
    """
    Gain net si on déplace notre récolteuse de (ox,oy) vers (dx,dy).
    = gain_placement(dest) [après retrait de l'origine]
      - rendement_actuel(origine) [ce qu'on perd en quittant]
    """
    carte_obj = maps['obj']
    if carte_obj[dy][dx] != 'X':
        return -999.0  # destination occupée

    # Ce que notre récolteuse gagne actuellement à l'origine
    rend_orig = rendement_actuel(ox, oy, maps, mon_id, dns_eff)

    # Simuler le départ de l'origine
    carte_obj[oy][ox] = 'X'
    # Gain net à la destination (nos alliés libérés à l'origine bénéficient aussi,
    # mais c'est un gain "global" qu'on ne comptabilise pas ici pour rester conservateur)
    gain_dest = gain_placement(dx, dy, maps, mon_id, dns_eff)
    # Restaurer
    carte_obj[oy][ox] = str(mon_id)

    return gain_dest - rend_orig

# ── Meilleurs emplacements pour nouvelles récolteuses ───────

def find_best_locations(maps, mon_id, top_n=20, exclues=None):
    """
    Retourne les top_n cases libres triées par gain_placement décroissant.
    """
    carte_obj = maps['obj']
    dns_eff   = apply_bonus_factories(maps)
    exclues   = exclues or set()

    emplacements = []
    for y in range(ROWS):
        for x in range(COLS):
            if carte_obj[y][x] != 'X': continue
            if (x, y) in exclues:      continue

            gain = gain_placement(x, y, maps, mon_id, dns_eff)

            emplacements.append({
                "coords":  (x, y),
                "gain":    gain,
                "secteur": get_secteur_de_case(x, y)
            })

    emplacements.sort(key=lambda i: i['gain'], reverse=True)
    top = emplacements[:top_n]

    stats = {i: {"count":0,"score_total":0} for i in range(4)}
    for p in top:
        stats[p["secteur"]]["count"]       += 1
        stats[p["secteur"]]["score_total"] += p["gain"]

    classement = sorted(
        [{"secteur":s,"nombre_de_spots":v["count"],"score_cumule":v["score_total"]}
         for s,v in stats.items()],
        key=lambda s: (s["nombre_de_spots"],s["score_cumule"]),
        reverse=True
    )
    return {"top_spots": top, "classement_secteurs": classement}

# ── Meilleurs déplacements ──────────────────────────────────

def find_best_moves(maps, mon_id, top_n=10):
    """
    Pour chaque récolteuse alliée, cherche le meilleur déplacement possible.
    Retourne [{"orig":(x,y), "dest":(x,y), "gain":float}, ...] trié par gain desc.
    """
    carte_obj  = maps['obj']
    dns_eff    = apply_bonus_factories(maps)
    SEUIL_MOVE = 3.0  # gain minimum relevé pour éviter les micro-déplacements inutiles

    recolteuses = [
        (x, y) for y in range(ROWS) for x in range(COLS)
        if carte_obj[y][x] == str(mon_id)
    ]

    candidats = []
    for ox, oy in recolteuses:
        meilleur_gain  = SEUIL_MOVE
        meilleure_dest = None
        for ty in range(ROWS):
            for tx in range(COLS):
                if carte_obj[ty][tx] != 'X': continue
                g = gain_deplacement(ox, oy, tx, ty, maps, mon_id, dns_eff)
                if g > meilleur_gain:
                    meilleur_gain  = g
                    meilleure_dest = (tx, ty)
        if meilleure_dest:
            candidats.append({
                "orig": (ox, oy),
                "dest": meilleure_dest,
                "gain": meilleur_gain
            })

    candidats.sort(key=lambda c: c['gain'], reverse=True)
    return candidats[:top_n]

# ── Meilleur emplacement usine ──────────────────────────────

def find_best_factory_spot(maps, mon_id, exclues=None):
    """
    Meilleure case libre pour une usine.
    BUGFIX v2 : on n'accepte de poser une usine que si on a PLUS d'alliés
    que d'ennemis dans le rayon 2, sinon on booste les adversaires autant que soi.
    Score = gain_net_allies - malus_ennemis (fortement pénalisé).
    """
    carte_obj = maps['obj']
    dns_eff   = apply_bonus_factories(maps)
    exclues   = exclues or set()

    meilleur_spot  = None
    meilleur_score = 0

    for y in range(ROWS):
        for x in range(COLS):
            if carte_obj[y][x] != 'X': continue
            if (x, y) in exclues:      continue
            zone = get_hex_neighbors_radius2(x, y)

            # Pas d'usine déjà dans la zone
            if any(carte_obj[vy][vx] == 'U' for vx,vy in zone):
                continue

            allies  = 0
            ennemis = 0
            gain_allies  = 0.0
            gain_ennemis = 0.0

            for vx, vy in zone:
                elem = carte_obj[vy][vx]
                if elem == str(mon_id):
                    allies += 1
                    gain_allies  += dns_eff[vy][vx]
                elif elem.isdigit():
                    ennemis += 1
                    gain_ennemis += dns_eff[vy][vx]

            # Condition : au moins 1 allié ET majorité alliée dans la zone
            if allies < 1 or allies <= ennemis:
                continue

            # Score = ce qu'on gagne en plus - ce qu'on donne aux ennemis
            # Le doublement bénéficie à tout le monde, on pénalise donc fortement
            # les cases où les ennemis récoltent beaucoup.
            score = gain_allies - gain_ennemis * 1.5
            if score > meilleur_score:
                meilleur_score = score
                meilleur_spot  = (x, y)

    return {"coords": meilleur_spot, "score_rentabilite": meilleur_score}

# ── Sabotage ────────────────────────────────────────────────

def strategic_sabotage_advance(maps, mon_id, classement_ennemis):
    """
    Identifie le(s) meilleur(s) secteur(s) à saboter.
    Priorité : secteur du leader, secteurs à forte densité ennemie.
    On évite de saboter un secteur où on est seul (gâchis).
    """
    carte_obj = maps['obj']
    if not classement_ennemis: return []
    leader_id = classement_ennemis[0]["id_joueur"]

    stats = {i:{'ennemis':0,'allies':0,'leader':0} for i in range(4)}
    total_allies = 0
    for y in range(ROWS):
        for x in range(COLS):
            elem = carte_obj[y][x]
            if not elem.isdigit(): continue
            sec = get_secteur_de_case(x, y)
            if elem == str(mon_id):
                stats[sec]['allies'] += 1; total_allies += 1
            else:
                stats[sec]['ennemis'] += 1
                if elem == leader_id: stats[sec]['leader'] += 1

    cibles = []
    for sec, s in stats.items():
        if s['ennemis'] == 0: continue
        # Ne pas saboter si on est le SEUL présent (on se tirerait une balle dans le pied)
        if s['allies'] > 0 and s['allies'] == total_allies: continue

        gains  = (s['ennemis'] - s['leader']) * 1 + s['leader'] * 3
        # Pertes : proportionnelles à nos alliés dans le secteur sabotés
        pertes = s['allies'] * (8 / max(total_allies, 1))
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

# ── Évacuation ──────────────────────────────────────────────

def evacuation_protocol(maps, mon_id, alertes_secteurs):
    """
    Déplace les récolteuses en DANGER vers des zones sûres.
    Retourne [{"orig_x","orig_y","dest_x","dest_y"}, ...]
    """
    carte_obj = maps['obj']
    secteurs_dangereux = {i for i in range(4) if alertes_secteurs[i]=='DANGER'}
    if not secteurs_dangereux: return []

    en_danger = [(x,y) for y in range(ROWS) for x in range(COLS)
                 if carte_obj[y][x] == str(mon_id)
                 and get_secteur_de_case(x,y) in secteurs_dangereux]
    if not en_danger: return []

    dns_eff = apply_bonus_factories(maps)
    spots_surs = sorted(
        [{"coords":(x,y),
          "gain": gain_placement(x,y,maps,mon_id,dns_eff)}
         for y in range(ROWS) for x in range(COLS)
         if carte_obj[y][x] == 'X'
         and get_secteur_de_case(x,y) not in secteurs_dangereux],
        key=lambda s: s["gain"], reverse=True
    )

    ordres  = []
    utilises = set()
    for ox, oy in en_danger:
        for spot in spots_surs:
            coords = spot["coords"]
            if coords not in utilises:
                ordres.append({"orig_x":ox,"orig_y":oy,
                               "dest_x":coords[0],"dest_y":coords[1]})
                utilises.add(coords)
                break
    return ordres