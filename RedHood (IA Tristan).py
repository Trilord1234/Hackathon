# ============================================================
#  RedHood — IA For The Spice  (v2)
# ============================================================
#
#  COÛTS RÉELS (selon le tableau des commandes)
#    Récolteuse  : 3 000
#    Usine       : 5 000
#    Ornithoptère: 400
#    Sabotage    : 600
#    Déplacement : GRATUIT
#
#  CHANGEMENTS v2 vs v1
#  ────────────────────
#  • BUGFIX : rendement_actuel() séparé pour gain_deplacement (plus de +1 fictif)
#  • BUGFIX : usines uniquement si allies > ennemis dans le rayon
#  • Sabotage dès le tour 25 (au lieu de 50)
#  • 3 récolteuses/tour en expansion (au lieu de 2)
#  • Déplacements optimisants dès le tour 6 (au lieu de 16)
#  • Réserve réduite à 1 000 (coûts bas le justifient)
#  • Sabotage en phase finale : budget_min = 1× (plus agressif)
#  • Récupération d'actions restantes : si des actions sont libres
#    en fin de tour, on tente des récolteuses supplémentaires
#
#  STRATÉGIE EN 3 PHASES
#  ─────────────────────
#  EXPANSION  (tours 1–15)
#    • 3 récolteuses/tour dans les meilleurs secteurs libres
#    • Diversification : max 1 par secteur par tour en expansion
#    • Orni sur chaque secteur occupé dès le 1er tour avec récolteuses
#    • Déplacements dès le tour 6 si gain > seuil
#
#  EXPLOITATION  (tours 16–150)
#    • Jusqu'à 5 récolteuses/tour (budget-limité)
#    • Max 2 récolteuses par secteur par tour
#    • Vol actif : se poser à côté d'ennemis si gain net positif
#    • Usines dès que allies > ennemis dans rayon 2
#    • Sabotages à partir du tour 25
#
#  FINALE  (tours 151–200)
#    • Plus de nouvelles récolteuses (risque ver trop élevé)
#    • Déplacements uniquement (gratuits et sûrs)
#    • Sabotages agressifs, ornis sur tout
#
# ============================================================

import socket

from Maps import (
    maps, update_map, get_my_spice, classify_threats_scores,
    find_best_locations, find_best_factory_spot, find_best_moves,
    strategic_sabotage_advance, evacuation_protocol,
    get_secteur_de_case, apply_bonus_factories, gain_placement
)

# ── Configuration ──────────────────────────────────────────
HOST      = "127.0.0.1"
PORT      = 1234
TEAM_NAME = "RedHood"

# ── Coûts ──────────────────────────────────────────────────
COUT_RECOLTEUSE = 3_000
COUT_USINE      = 5_000
COUT_ORNI       = 400
COUT_SABOTAGE   = 600
RESERVE         = 1_000   # réduit de 1500→1000 : coûts bas le justifient

# ── Paramètres jeu ─────────────────────────────────────────
MAX_ACTIONS        = 15
ROWS, COLS         = 16, 18
PHASE_DEPLACEMENTS = 6    # v2 : déplacements dès tour 6 (vs 16 avant)
PHASE_EXPLOITATION = 16
PHASE_SABOTAGE     = 25   # v2 : sabotage dès tour 25 (vs 50 avant)
PHASE_FINALE       = 151

MAX_RECOLT_PAR_SECTEUR = 6


# ==============================================================
#  Couche réseau
# ==============================================================

class GameClient:
    def __init__(self, host, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.buffer = ""

    def recv_line(self, timeout=4.5):
        self.sock.settimeout(timeout)
        while '\n' not in self.buffer:
            try:
                chunk = self.sock.recv(4096).decode('utf-8')
                if not chunk:
                    raise ConnectionError("Connexion fermée.")
                self.buffer += chunk
            except socket.timeout:
                break
        if '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            return line.strip()
        line, self.buffer = self.buffer, ""
        return line.strip()

    def send(self, msg):
        self.sock.sendall((msg + '\n').encode('utf-8'))

    def command(self, msg):
        self.send(msg)
        return self.recv_line()


# ==============================================================
#  RedHood
# ==============================================================

class RedHood:
    def __init__(self):
        self.client     = GameClient(HOST, PORT)
        self.mon_id     = None
        self.epice      = 0
        self.tour       = 0
        self.nb_actions = 0

        self.maps               = maps
        self.classement_ennemis = []
        self.ornithopteres      = {0:0, 1:0, 2:0, 3:0}

        self.spots_recolt_tour  = set()
        self.spots_usines_tour  = set()
        self.sabotages_tour     = set()
        self.deplacements_tour  = set()

    # ── Connexion ───────────────────────────────────────────

    def connect(self):
        msg = self.client.recv_line()
        if msg != "NOM_EQUIPE":
            raise RuntimeError(f"Inattendu : {msg!r}")
        rep = self.client.command(TEAM_NAME)
        self.mon_id = str(rep.split('|')[-1].strip())
        print(f"[RedHood] Joueur {self.mon_id}")

    # ── Quota d'actions ────────────────────────────────────

    def envoyer(self, msg):
        if self.nb_actions >= MAX_ACTIONS:
            return None
        rep = self.client.command(msg)
        self.nb_actions += 1
        return rep

    def action_ok(self, msg):
        rep = self.envoyer(msg)
        return rep is not None and rep.startswith("OK")

    def restantes(self):
        return MAX_ACTIONS - self.nb_actions

    def budget(self):
        """Épice utilisable au-dessus de la réserve."""
        return max(0, self.epice - RESERVE)

    # ── Utilitaires carte ───────────────────────────────────

    def mes_recolteuses(self):
        return [(x,y) for y in range(ROWS) for x in range(COLS)
                if self.maps['obj'][y][x] == str(self.mon_id)]

    def recolteuses_par_secteur(self):
        count = {i:0 for i in range(4)}
        for x,y in self.mes_recolteuses():
            count[get_secteur_de_case(x,y)] += 1
        return count

    # ── Tick ornithoptères ──────────────────────────────────

    def tick_ornis(self):
        for sec in range(4):
            if self.ornithopteres[sec] > 0:
                self.ornithopteres[sec] -= 1

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 0 — État du monde
    #  Action 1 : ELEMENTS  (toujours)
    #  Action 2 : DENSITE   (tour 1) | SCORES (tours ≥ 2)
    # ══════════════════════════════════════════════════════════

    def etape_etat(self):
        rep = self.envoyer("ELEMENTS")
        if rep and len(rep) == 288:
            update_map("ELEMENTS", rep, self.maps)

        if self.tour == 1:
            rep = self.envoyer("DENSITE")
            if rep and len(rep) == 288:
                update_map("DENSITE", rep, self.maps)
            self.epice = 1_000_000
            self.classement_ennemis = []
        else:
            rep = self.envoyer("SCORES")
            if rep:
                self.epice              = get_my_spice(rep, self.mon_id)
                self.classement_ennemis = classify_threats_scores(rep, self.mon_id)

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 1 — WARNING (si orni actif)
    # ══════════════════════════════════════════════════════════

    def etape_warnings(self):
        if self.restantes() < 2:
            return ['INCONNU'] * 4
        if not any(v > 0 for v in self.ornithopteres.values()):
            return ['INCONNU'] * 4
        rep = self.envoyer("WARNING")
        if not rep: return ['INCONNU'] * 4
        parts = [p.strip() for p in rep.split('|')]
        return parts if len(parts) == 4 else ['INCONNU'] * 4

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 2 — Ornithoptères
    #  Déployer sur chaque secteur occupé sans surveillance.
    # ══════════════════════════════════════════════════════════

    def etape_ornithopteres(self):
        count = self.recolteuses_par_secteur()
        for sec in sorted(count, key=lambda s: count[s], reverse=True):
            if self.restantes() < 2: break
            if count[sec] > 0 and self.ornithopteres[sec] == 0:
                if self.budget() >= COUT_ORNI:
                    if self.action_ok(f"AJOUTERORNI|{sec}"):
                        self.ornithopteres[sec] = 5
                        self.epice -= COUT_ORNI
                        print(f"[RedHood]  Orni sect={sec}")

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 3 — Évacuation d'urgence (DANGER détecté)
    # ══════════════════════════════════════════════════════════

    def etape_evacuation(self, alertes):
        ordres = evacuation_protocol(self.maps, self.mon_id, alertes)
        for o in ordres:
            if self.restantes() < 2: break
            if (o['orig_x'], o['orig_y']) in self.deplacements_tour: continue
            cmd = (f"DEPLACER|{o['orig_y']}|{o['orig_x']}"
                   f"|{o['dest_y']}|{o['dest_x']}")
            if self.action_ok(cmd):
                self.maps['obj'][o['orig_y']][o['orig_x']] = 'X'
                self.maps['obj'][o['dest_y']][o['dest_x']] = str(self.mon_id)
                self.deplacements_tour.add((o['orig_x'], o['orig_y']))
                self.spots_recolt_tour.add((o['dest_x'], o['dest_y']))
                print(f"[RedHood]  Évac ({o['orig_x']},{o['orig_y']})"
                      f"→({o['dest_x']},{o['dest_y']})")

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 4 — Déplacements optimisants
    #  v2 : actifs dès le tour PHASE_DEPLACEMENTS (6) au lieu de 16.
    #  Seuil move relevé à 3.0 pour éviter les micro-réoptimisations inutiles.
    # ══════════════════════════════════════════════════════════

    def etape_deplacements(self):
        if self.restantes() < 3: return
        if self.tour < PHASE_DEPLACEMENTS: return

        max_moves = self.restantes() // 2 if self.tour < PHASE_FINALE else self.restantes() - 1

        candidats = find_best_moves(self.maps, self.mon_id, top_n=max_moves)

        for c in candidats:
            if self.restantes() < 2: break
            ox, oy = c['orig']
            dx, dy = c['dest']
            if (ox, oy) in self.deplacements_tour: continue
            if self.maps['obj'][oy][ox] != str(self.mon_id): continue
            if self.maps['obj'][dy][dx] != 'X': continue
            if self.action_ok(f"DEPLACER|{oy}|{ox}|{dy}|{dx}"):
                self.maps['obj'][oy][ox] = 'X'
                self.maps['obj'][dy][dx] = str(self.mon_id)
                self.deplacements_tour.add((ox, oy))
                self.spots_recolt_tour.add((dx, dy))
                print(f"[RedHood]  Move ({ox},{oy})→({dx},{dy}) gain={c['gain']:.1f}")

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 5 — Usines
    #  v2 : posées uniquement si allies > ennemis dans le rayon 2
    #  (sinon on booste les adversaires gratuitement).
    # ══════════════════════════════════════════════════════════

    def etape_usines(self):
        if len(self.mes_recolteuses()) < 2: return

        for _ in range(2):
            if self.restantes() < 2: break
            if self.budget() < COUT_USINE: break
            spot = find_best_factory_spot(
                self.maps, self.mon_id, exclues=self.spots_usines_tour
            )
            if spot["coords"] is None or spot["score_rentabilite"] <= 0:
                break
            x, y = spot["coords"]
            if self.action_ok(f"AJOUTERUSINE|{y}|{x}"):
                self.maps['obj'][y][x] = 'U'
                self.epice -= COUT_USINE
                self.spots_usines_tour.add((x, y))
                print(f"[RedHood]  Usine ({x},{y}) score={spot['score_rentabilite']:.0f}")

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 6 — Nouvelles récolteuses
    #  v2 : 3 récolteuses/tour en expansion (au lieu de 2).
    #  Diversification : max 1 par secteur par tour en expansion.
    # ══════════════════════════════════════════════════════════

    def etape_recolteuses(self, max_supplementaire=0):
        if self.tour >= PHASE_FINALE: return
        if self.budget() < COUT_RECOLTEUSE or self.restantes() < 2: return

        SEUIL_MIN_GAIN = 4.0   # légèrement abaissé pour être plus agressif

        # v2 : 3/tour en expansion, 5/tour en exploitation, +bonus si actions libres
        max_ce_tour      = 3 if self.tour < PHASE_EXPLOITATION else 5
        max_ce_tour     += max_supplementaire
        max_par_sec_tour = 1 if self.tour < PHASE_EXPLOITATION else 2

        posees         = 0
        posees_par_sec = {0:0, 1:0, 2:0, 3:0}
        count_global   = self.recolteuses_par_secteur()

        result = find_best_locations(
            self.maps, self.mon_id,
            top_n=60, exclues=self.spots_recolt_tour
        )

        for spot in result["top_spots"]:
            if posees >= max_ce_tour: break
            if self.restantes() < 2 or self.budget() < COUT_RECOLTEUSE: break

            x, y  = spot["coords"]
            sec   = spot["secteur"]
            gain  = spot["gain"]

            if gain < SEUIL_MIN_GAIN: break

            if self.maps['obj'][y][x] != 'X': continue
            if (x, y) in self.spots_recolt_tour: continue
            if posees_par_sec[sec] >= max_par_sec_tour: continue
            if count_global[sec] >= MAX_RECOLT_PAR_SECTEUR: continue

            # Diversification forcée en expansion : 1 seul par secteur par tour
            if self.tour < PHASE_EXPLOITATION and posees_par_sec[sec] >= 1:
                continue

            if self.action_ok(f"AJOUTERRECOLTEUSE|{y}|{x}"):
                self.maps['obj'][y][x] = str(self.mon_id)
                self.epice -= COUT_RECOLTEUSE
                self.spots_recolt_tour.add((x, y))
                posees += 1
                posees_par_sec[sec] += 1
                count_global[sec]   += 1
                print(f"[RedHood]  Recolt ({x},{y}) sec={sec} gain={gain:.1f}")

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 7 — Sabotages
    #  v2 : dès le tour PHASE_SABOTAGE (25), budget_min plus souple en finale.
    # ══════════════════════════════════════════════════════════

    def etape_sabotage(self):
        if self.tour < PHASE_SABOTAGE: return
        if not self.classement_ennemis: return
        if len(self.mes_recolteuses()) < 2: return

        max_sab    = 1 if self.tour < PHASE_FINALE else 2
        # v2 : budget_min plus agressif en finale (1× au lieu de 3×)
        budget_min = COUT_SABOTAGE * 2 if self.tour < PHASE_FINALE else COUT_SABOTAGE

        if self.budget() < budget_min: return

        cibles     = strategic_sabotage_advance(
            self.maps, self.mon_id, self.classement_ennemis
        )
        sabs_poses = 0
        for cible in cibles:
            if sabs_poses >= max_sab: break
            if self.restantes() < 2 or self.budget() < COUT_SABOTAGE: break
            sec = cible["secteur"]
            if sec in self.sabotages_tour: continue
            if self.action_ok(f"SABOTER|{sec}"):
                self.epice -= COUT_SABOTAGE
                self.sabotages_tour.add(sec)
                sabs_poses += 1
                print(f"[RedHood]  Sabotage sect={sec}"
                      f" score={cible['score_cible']:.1f}"
                      f" (leader={cible['dont_leader']})")

    # ══════════════════════════════════════════════════════════
    #  ÉTAPE 8 — Récupération d'actions restantes
    #  v2 : si on a encore des actions et du budget, on pose des récolteuses
    #  supplémentaires plutôt que de laisser le quota se perdre.
    # ══════════════════════════════════════════════════════════

    def etape_recuperation(self):
        if self.tour >= PHASE_FINALE: return
        actions_libres = self.restantes() - 1  # garder 1 pour FINDETOUR
        if actions_libres <= 0: return
        if self.budget() < COUT_RECOLTEUSE: return
        # On tente des récolteuses bonus avec les actions restantes
        extras = actions_libres // 1  # chaque récolteuse coûte 1 action
        if extras > 0:
            self.etape_recolteuses(max_supplementaire=extras)

    # ══════════════════════════════════════════════════════════
    #  Boucle principale
    # ══════════════════════════════════════════════════════════

    def play_turn(self, numero_tour):
        self.tour       = numero_tour
        self.nb_actions = 0
        self.spots_recolt_tour  = set()
        self.spots_usines_tour  = set()
        self.sabotages_tour     = set()
        self.deplacements_tour  = set()

        phase = ("EXPANSION"    if numero_tour < PHASE_EXPLOITATION else
                 "FINALE"       if numero_tour >= PHASE_FINALE else
                 "EXPLOITATION")

        print(f"\n{'='*55}")
        print(f"  RedHood v2 | Tour {numero_tour} | J{self.mon_id} | {phase}")
        print(f"{'='*55}")

        self.tick_ornis()

        # 1. État (actions 1-2)
        self.etape_etat()
        print(f"  Épice={self.epice:,}  Récolt.={len(self.mes_recolteuses())}"
              f"  Restantes={self.restantes()}")

        # 2. Warnings (action 3 si orni actif)
        alertes = self.etape_warnings()
        if any(a != 'INCONNU' for a in alertes):
            print(f"  Alertes : {alertes}")

        # 3. Ornithoptères
        self.etape_ornithopteres()

        # 4. Évacuation urgente (DANGER)
        self.etape_evacuation(alertes)

        # 5. Déplacements optimisants (gratuits, dès tour 6)
        self.etape_deplacements()

        # 6. Usines (avant récolteuses pour prioriser le budget)
        self.etape_usines()

        # 7. Récolteuses
        self.etape_recolteuses()

        # 8. Sabotages
        self.etape_sabotage()

        # 9. Récupération d'actions restantes → récolteuses bonus
        self.etape_recuperation()

        # 10. Fin de tour (hors quota)
        self.client.command("FINDETOUR")

        print(f"  → {self.nb_actions}/{MAX_ACTIONS} actions | épice≈{self.epice:,}")

    def run(self):
        self.connect()
        while True:
            msg = self.client.recv_line(timeout=60)
            if not msg:
                print("[RedHood] Fin de partie.")
                break
            if msg.startswith("DEBUT_TOUR"):
                try:
                    num = int(msg.split('|')[1])
                except (IndexError, ValueError):
                    num = self.tour + 1
                self.play_turn(num)
            else:
                print(f"[RedHood] Inconnu : {msg!r}")


# ==============================================================

if __name__ == "__main__":
    ai = RedHood()
    try:
        ai.run()
    except KeyboardInterrupt:
        print("\n[RedHood] Arrêt.")
    except Exception as e:
        print(f"[RedHood] Erreur : {e}")
        raise