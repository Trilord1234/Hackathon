#!/usr/bin/env python3
# ============================================================
#  RedHood — IA For The Spice
# ============================================================
#
#  STRATÉGIE GÉNÉRALE
#  ──────────────────
#  Phase EXPANSION  (tours 1-10)
#    → Poser 1 récolteuse par tour en ciblant systématiquement
#      des secteurs différents (diversification).
#    → Déployer des ornithoptères sur tous les secteurs occupés.
#    → Réserver du budget pour la 1ère usine dès tour 3.
#
#  Phase EXPLOITATION  (tours 11-150)
#    → Remplir les secteurs rentables jusqu'à saturation utile.
#    → Construire des usines dès qu'on a ≥2 alliés dans le rayon.
#    → WARNING chaque tour → évacuer si DANGER.
#    → Sabotage léger si on est en tête et qu'on a de la marge.
#
#  Phase FINALE  (tours 151-200)
#    → Plus de nouvelles récolteuses (risque ver trop élevé).
#    → Sabotages agressifs sur le leader.
#    → Évacuations maximales.
#
#  RÈGLE BUDGET
#    → On réserve toujours 10 000 d'épice (sécurité pour 2 ornis
#      ou 1 évacuation + 1 action).
#    → On pose une usine AVANT les récolteuses supplémentaires
#      si le score d'usine est positif.
#
# ============================================================

import socket

from Maps import (
    maps, update_map, get_my_spice, classify_threats_scores,
    find_best_locations, find_best_factory_spot,
    strategic_sabotage_advance, evacuation_protocol,
    get_secteur_de_case, apply_bonus_factories
)

# -------- Configuration --------
HOST      = "127.0.0.1"
PORT      = 1234
TEAM_NAME = "RedHood"      # < 15 caractères

# -------- Constantes -----------
COUT_ACTION  = 5000
MAX_ACTIONS  = 15
ROWS, COLS   = 16, 18
RESERVE      = 10_000   # budget minimal conservé en permanence

PHASE_EXPLOITATION = 11   # tour à partir duquel on passe en exploitation
PHASE_FINALE       = 151  # tour à partir duquel on devient agressif/défensif


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
        self.client   = GameClient(HOST, PORT)
        self.mon_id   = None
        self.epice    = 0
        self.tour     = 0
        self.nb_actions = 0

        self.maps               = maps
        self.classement_ennemis = []

        # Ornithoptères : tours restants par secteur
        self.ornithopteres = {0: 0, 1: 0, 2: 0, 3: 0}

        # Ensembles pour éviter les doublons intra-tour
        self.spots_recolteuses_tour = set()   # cases réservées pour récolteuses
        self.spots_usines_tour      = set()   # cases réservées pour usines
        self.sabotages_tour         = set()

    # ----------------------------------------------------------
    #  Connexion
    # ----------------------------------------------------------

    def connect(self):
        msg = self.client.recv_line()
        if msg != "NOM_EQUIPE":
            raise RuntimeError(f"Message inattendu : {msg!r}")
        rep = self.client.command(TEAM_NAME)
        self.mon_id = str(rep.split('|')[-1].strip())
        print(f"[RedHood] Connecté → joueur {self.mon_id}")

    # ----------------------------------------------------------
    #  Gestion du quota d'actions
    # ----------------------------------------------------------

    def envoyer(self, msg):
        """Envoie une commande/demande, incrémente le compteur, retourne la réponse."""
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

    def budget_disponible(self):
        """Épice utilisable = stock - réserve de sécurité."""
        return max(0, self.epice - RESERVE)

    # ----------------------------------------------------------
    #  Utilitaires carte
    # ----------------------------------------------------------

    def mes_recolteuses(self):
        return [
            (x, y)
            for y in range(ROWS) for x in range(COLS)
            if self.maps['obj'][y][x] == str(self.mon_id)
        ]

    def nb_recolteuses_par_secteur(self):
        count = {i: 0 for i in range(4)}
        for x, y in self.mes_recolteuses():
            count[get_secteur_de_case(x, y)] += 1
        return count

    # ----------------------------------------------------------
    #  Étape 0 : Récupérer l'état
    #  Action 1 : ELEMENTS (toujours)
    #  Action 2 : DENSITE (tour 1 seulement) | SCORES (tours suivants)
    # ----------------------------------------------------------

    def etape_etat(self):
        # Action 1 — ELEMENTS
        rep = self.envoyer("ELEMENTS")
        if rep and len(rep) == 288:
            update_map("ELEMENTS", rep, self.maps)

        # Action 2 — DENSITE (tour 1) ou SCORES (tours ≥ 2)
        if self.tour == 1:
            rep = self.envoyer("DENSITE")
            if rep and len(rep) == 288:
                update_map("DENSITE", rep, self.maps)
            self.epice = 1_000_000  # stock de départ selon les règles
            self.classement_ennemis = []
        else:
            rep = self.envoyer("SCORES")
            if rep:
                self.epice             = get_my_spice(rep, self.mon_id)
                self.classement_ennemis = classify_threats_scores(rep, self.mon_id)

    # ----------------------------------------------------------
    #  Étape 1 : Warnings
    # ----------------------------------------------------------

    def etape_warnings(self):
        """Demande WARNING si au moins 1 orni actif. 1 action consommée."""
        if self.restantes() < 2:
            return ['INCONNU'] * 4
        if not any(v > 0 for v in self.ornithopteres.values()):
            return ['INCONNU'] * 4
        rep = self.envoyer("WARNING")
        if not rep:
            return ['INCONNU'] * 4
        parts = [p.strip() for p in rep.split('|')]
        return parts if len(parts) == 4 else ['INCONNU'] * 4

    # ----------------------------------------------------------
    #  Étape 2 : Ornithoptères
    #  On déploie sur TOUS les secteurs occupés sans surveillance.
    # ----------------------------------------------------------

    def etape_ornithopteres(self):
        count = self.nb_recolteuses_par_secteur()
        for sec in sorted(count, key=lambda s: count[s], reverse=True):
            if self.restantes() < 2:
                break
            if count[sec] > 0 and self.ornithopteres[sec] == 0:
                if self.action_ok(f"AJOUTERORNI|{sec}"):
                    self.ornithopteres[sec] = 5
                    print(f"[RedHood]  Orni → secteur {sec}")

    def tick_ornithopteres(self):
        for sec in range(4):
            if self.ornithopteres[sec] > 0:
                self.ornithopteres[sec] -= 1

    # ----------------------------------------------------------
    #  Étape 3 : Évacuation d'urgence
    # ----------------------------------------------------------

    def etape_evacuation(self, alertes):
        ordres = evacuation_protocol(self.maps, self.mon_id, alertes)
        for ordre in ordres:
            if self.restantes() < 2:
                break
            cmd = (f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}"
                   f"|{ordre['dest_y']}|{ordre['dest_x']}")
            if self.action_ok(cmd):
                self.maps['obj'][ordre['orig_y']][ordre['orig_x']] = 'X'
                self.maps['obj'][ordre['dest_y']][ordre['dest_x']] = str(self.mon_id)
                # Le spot de destination est maintenant occupé
                self.spots_recolteuses_tour.add((ordre['dest_x'], ordre['dest_y']))
                print(f"[RedHood]  Fuite ({ordre['orig_x']},{ordre['orig_y']})"
                      f" → ({ordre['dest_x']},{ordre['dest_y']})")

    # ----------------------------------------------------------
    #  Étape 4 : Usines  (AVANT les nouvelles récolteuses)
    #
    #  On pose une usine si :
    #   - On a ≥ 2 récolteuses sur la carte
    #   - Le score est positif
    #   - Budget dispo ≥ COUT_ACTION
    #  On peut poser jusqu'à 2 usines par tour.
    # ----------------------------------------------------------

    def etape_usines(self):
        if len(self.mes_recolteuses()) < 2:
            return

        for _ in range(2):
            if self.restantes() < 2 or self.budget_disponible() < COUT_ACTION:
                break
            spot = find_best_factory_spot(
                self.maps, self.mon_id,
                usines_deja_choisies=self.spots_usines_tour
            )
            if spot["coords"] is None or spot["score_rentabilite"] <= 0:
                break
            x, y = spot["coords"]
            if self.action_ok(f"AJOUTERUSINE|{y}|{x}"):
                self.maps['obj'][y][x] = 'U'
                self.epice -= COUT_ACTION
                self.spots_usines_tour.add((x, y))
                print(f"[RedHood]  Usine en ({x},{y}) score={spot['score_rentabilite']:.0f}")

    # ----------------------------------------------------------
    #  Étape 5 : Placement de récolteuses
    #
    #  Stratégie de diversification :
    #   - Phase expansion  : 1 récolteuse dans le secteur le plus rentable,
    #                        puis 1 dans un secteur différent si budget ok.
    #   - Phase exploitation : jusqu'à 3 récolteuses par tour,
    #                         max 3 par secteur par tour pour éviter le clustering.
    #   - Phase finale : aucune nouvelle récolteuse (trop risqué).
    #
    #  Le score anti-clustering est géré dans find_best_locations.
    #  On passe cases_deja_choisies pour éviter de choisir 2× la même case.
    # ----------------------------------------------------------

    def etape_recolteuses(self):
        if self.tour >= PHASE_FINALE:
            return  # phase finale : on ne pose plus rien

        if self.budget_disponible() < COUT_ACTION or self.restantes() < 2:
            return

        # Nombre max de récolteuses à poser ce tour selon la phase
        if self.tour <= PHASE_EXPLOITATION:
            max_ce_tour = 2   # expansion : 1-2 par tour
        else:
            max_ce_tour = 4   # exploitation : jusqu'à 4

        max_par_secteur = 2 if self.tour <= PHASE_EXPLOITATION else 3

        posees_ce_tour  = 0
        posees_par_sec  = {0: 0, 1: 0, 2: 0, 3: 0}

        # On récupère les meilleurs spots (anti-clustering inclus)
        result = find_best_locations(
            self.maps, self.mon_id, top_n=50,
            cases_deja_choisies=self.spots_recolteuses_tour
        )

        for spot in result["top_spots"]:
            if posees_ce_tour >= max_ce_tour:
                break
            if self.restantes() < 2 or self.budget_disponible() < COUT_ACTION:
                break

            x, y = spot["coords"]
            sec  = spot["secteur"]

            if self.maps['obj'][y][x] != 'X':
                continue
            if (x, y) in self.spots_recolteuses_tour:
                continue
            if posees_par_sec[sec] >= max_par_secteur:
                continue
            # En phase d'expansion, forcer la diversification :
            # si on a déjà posé 1 récolteuse ce tour, le 2ème doit être
            # dans un secteur différent du 1er posé.
            if self.tour <= PHASE_EXPLOITATION and posees_ce_tour == 1:
                if posees_par_sec[sec] > 0:
                    continue  # même secteur que le 1er → passer

            if self.action_ok(f"AJOUTERRECOLTEUSE|{y}|{x}"):
                self.maps['obj'][y][x] = str(self.mon_id)
                self.epice -= COUT_ACTION
                self.spots_recolteuses_tour.add((x, y))
                posees_ce_tour  += 1
                posees_par_sec[sec] += 1
                print(f"[RedHood]  Récolteuse ({x},{y}) sec={sec}"
                      f" score={spot['score']:.0f} rendement={spot['rendement']}")

    # ----------------------------------------------------------
    #  Étape 6 : Sabotages
    #
    #  Tours 1-50   : pas de sabotage (construction)
    #  Tours 51-150 : sabotage si on est ≥ 2ème ET qu'on a largement > RESERVE
    #  Tours 151-200: sabotage agressif si on peut (phase finale)
    # ----------------------------------------------------------

    def etape_sabotage(self):
        if self.tour < 51:
            return
        if not self.classement_ennemis:
            return
        if len(self.mes_recolteuses()) < 2:
            return

        # Budget pour saboter : plus agressif en fin de partie
        budget_min = COUT_ACTION * 4 if self.tour < PHASE_FINALE else COUT_ACTION * 2
        if self.epice < budget_min:
            return

        cibles = strategic_sabotage_advance(
            self.maps, self.mon_id, self.classement_ennemis
        )
        for cible in cibles:
            if self.restantes() < 2 or self.budget_disponible() < COUT_ACTION:
                break
            sec = cible["secteur"]
            if sec in self.sabotages_tour:
                continue
            if self.action_ok(f"SABOTER|{sec}"):
                self.epice -= COUT_ACTION
                self.sabotages_tour.add(sec)
                print(f"[RedHood]  Sabotage sect={sec}"
                      f" score={cible['score_cible']:.1f}"
                      f" (leader={cible['dont_leader']} ennemis={cible['ennemis_detruits']})")

    # ----------------------------------------------------------
    #  Boucle principale
    # ----------------------------------------------------------

    def play_turn(self, numero_tour):
        self.tour       = numero_tour
        self.nb_actions = 0
        self.spots_recolteuses_tour = set()
        self.spots_usines_tour      = set()
        self.sabotages_tour         = set()

        phase = ("EXPANSION" if numero_tour <= PHASE_EXPLOITATION
                 else "FINALE" if numero_tour >= PHASE_FINALE
                 else "EXPLOITATION")

        print(f"\n{'='*55}")
        print(f"  RedHood | Tour {numero_tour} | Joueur {self.mon_id} | {phase}")
        print(f"{'='*55}")

        # Décrémenter les ornithoptères
        self.tick_ornithopteres()

        # 1. État  (actions 1-2)
        self.etape_etat()
        print(f"  Épice={self.epice:,} | Récolt.={len(self.mes_recolteuses())} "
              f"| Restantes={self.restantes()}")

        # 2. Warnings  (action 3 si orni actif)
        alertes = self.etape_warnings()
        if any(a != 'INCONNU' for a in alertes):
            print(f"  Alertes : {alertes}")

        # 3. Ornithoptères  (1 action par secteur non couvert)
        self.etape_ornithopteres()

        # 4. Évacuation  (1 action par récolteuse à déplacer)
        self.etape_evacuation(alertes)

        # 5. Usines  (AVANT les récolteuses pour réserver le budget)
        self.etape_usines()

        # 6. Récolteuses
        self.etape_recolteuses()

        # 7. Sabotages
        self.etape_sabotage()

        # 8. Fin de tour  (ne compte PAS dans les 15 actions)
        self.client.command("FINDETOUR")

        print(f"  → {self.nb_actions}/{MAX_ACTIONS} actions | "
              f"Épice finale ≈ {self.epice:,}")

    def run(self):
        self.connect()
        while True:
            msg = self.client.recv_line(timeout=60)
            if not msg:
                print("[RedHood] Fin de partie (pas de message).")
                break
            if msg.startswith("DEBUT_TOUR"):
                try:
                    num = int(msg.split('|')[1])
                except (IndexError, ValueError):
                    num = self.tour + 1
                self.play_turn(num)
            else:
                print(f"[RedHood] Message inconnu : {msg!r}")


# ==============================================================
#  Point d'entrée
# ==============================================================

if __name__ == "__main__":
    ai = RedHood()
    try:
        ai.run()
    except KeyboardInterrupt:
        print("\n[RedHood] Arrêt.")
    except Exception as e:
        print(f"[RedHood] Erreur fatale : {e}")
        raise