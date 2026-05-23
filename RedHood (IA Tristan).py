#!/usr/bin/env python3
# ============================================================
#  RedHood — IA For The Spice
# ============================================================
import socket

from Maps import (
    maps, update_map, get_my_spice, classify_threats_scores,
    find_best_locations, find_best_factory_spot,
    strategic_sabotage_advance, evacuation_protocol,
    get_secteur_de_case, apply_bonus_factories, get_hex_neighbors
)

# -------- Configuration --------
HOST      = "127.0.0.1"
PORT      = 1234
TEAM_NAME = "RedHood"      # < 15 caractères

# -------- Constantes -----------
COUT_ACTION = 5000
MAX_ACTIONS = 15           # quota serveur
ROWS, COLS  = 16, 18


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
                    raise ConnectionError("Connexion fermée par le serveur.")
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
        """Envoie une commande/demande et retourne la réponse brute."""
        self.send(msg)
        return self.recv_line()


# ==============================================================
#  Logique RedHood
# ==============================================================

class RedHood:
    def __init__(self):
        self.client   = GameClient(HOST, PORT)
        self.mon_id   = None
        self.epice    = 0
        self.tour     = 0

        # Compteur d'actions envoyées ce tour (hors FINDETOUR)
        self.nb_actions = 0

        # État du jeu
        self.maps               = maps
        self.classement_ennemis = []

        # Ornithoptères : nb de tours restants par secteur
        self.ornithopteres = {0: 0, 1: 0, 2: 0, 3: 0}

        # Sabotages déclenchés ce tour (pour ne pas doubler)
        self.sabotages_tour = set()

    # ----------------------------------------------------------
    #  Connexion
    # ----------------------------------------------------------

    def connect(self):
        msg = self.client.recv_line()
        if msg != "NOM_EQUIPE":
            raise RuntimeError(f"Message inattendu : {msg!r}")
        rep = self.client.command(TEAM_NAME)
        # "Bonjour RedHood vous êtes l'équipe |N"
        self.mon_id = str(rep.split('|')[-1].strip())
        print(f"[RedHood] Connecté → joueur {self.mon_id}")

    # ----------------------------------------------------------
    #  Envoi d'une action/demande avec comptage
    # ----------------------------------------------------------

    def envoyer(self, msg):
        """
        Envoie une commande ou demande, compte dans le quota, retourne la réponse.
        Retourne None si le quota est épuisé.
        """
        if self.nb_actions >= MAX_ACTIONS:
            print(f"[RedHood] ⚠ Quota atteint, impossible d'envoyer : {msg}")
            return None
        rep = self.client.command(msg)
        self.nb_actions += 1
        return rep

    def action_ok(self, msg):
        """Envoie une commande et retourne True si le serveur répond OK."""
        rep = self.envoyer(msg)
        return rep is not None and rep.startswith("OK")

    def restantes(self):
        """Actions encore disponibles ce tour."""
        return MAX_ACTIONS - self.nb_actions

    # ----------------------------------------------------------
    #  Utilitaires carte
    # ----------------------------------------------------------

    def mes_recolteuses(self):
        return [
            (x, y)
            for y in range(ROWS)
            for x in range(COLS)
            if self.maps['obj'][y][x] == str(self.mon_id)
        ]

    def mes_usines(self):
        return [
            (x, y)
            for y in range(ROWS)
            for x in range(COLS)
            if self.maps['obj'][y][x] == 'U'
        ]

    # ----------------------------------------------------------
    #  Décrément ornithoptères (à appeler en début de tour)
    # ----------------------------------------------------------

    def tick_ornithopteres(self):
        for sec in range(4):
            if self.ornithopteres[sec] > 0:
                self.ornithopteres[sec] -= 1

    # ----------------------------------------------------------
    #  Étape 0 : Récupérer l'état (ELEMENTS en 1er, puis DENSITE ou SCORES)
    # ----------------------------------------------------------

    def etape_recuperer_etat(self):
        """
        Tour 1  → ELEMENTS (action 1) + DENSITE   (action 2)
        Tour N  → ELEMENTS (action 1) + SCORES     (action 2)
        """
        # --- Action 1 : ELEMENTS (toujours) ---
        rep_elem = self.envoyer("ELEMENTS")
        if rep_elem:
            update_map("ELEMENTS", rep_elem, self.maps)

        # --- Action 2 : DENSITE (tour 1) ou SCORES (tours suivants) ---
        if self.tour == 1:
            rep_dns = self.envoyer("DENSITE")
            if rep_dns:
                update_map("DENSITE", rep_dns, self.maps)
            # On initialise l'épice à la valeur par défaut (inconnue)
            self.epice = 1_000_000  # valeur de départ selon les règles
            self.classement_ennemis = []
        else:
            rep_scores = self.envoyer("SCORES")
            if rep_scores:
                self.epice             = get_my_spice(rep_scores, self.mon_id)
                self.classement_ennemis = classify_threats_scores(rep_scores, self.mon_id)

    # ----------------------------------------------------------
    #  Étape 1 : Warnings (si au moins 1 ornithoptère actif)
    # ----------------------------------------------------------

    def etape_warnings(self):
        """Demande WARNING si au moins un orni est actif. Retourne liste de 4 statuts."""
        if self.restantes() <= 1:  # garder au moins 1 action pour FINDETOUR
            return ['INCONNU'] * 4
        if not any(v > 0 for v in self.ornithopteres.values()):
            return ['INCONNU'] * 4
        rep = self.envoyer("WARNING")
        if not rep:
            return ['INCONNU'] * 4
        parts = [p.strip() for p in rep.split('|')]
        if len(parts) != 4:
            return ['INCONNU'] * 4
        return parts

    # ----------------------------------------------------------
    #  Étape 2 : Ornithoptères
    # ----------------------------------------------------------

    def etape_ornithopteres(self):
        """
        Déploie des ornithoptères dans tous les secteurs où on a des récolteuses
        et où aucun orni n'est actif, dans la limite des actions restantes.
        """
        count = {i: 0 for i in range(4)}
        for x, y in self.mes_recolteuses():
            count[get_secteur_de_case(x, y)] += 1

        for sec in sorted(count, key=lambda s: count[s], reverse=True):
            if self.restantes() <= 1:
                break
            if count[sec] > 0 and self.ornithopteres[sec] == 0:
                if self.action_ok(f"AJOUTERORNI|{sec}"):
                    self.ornithopteres[sec] = 5
                    print(f"[RedHood]  Orni → secteur {sec}")

    # ----------------------------------------------------------
    #  Étape 3 : Évacuation d'urgence
    # ----------------------------------------------------------

    def etape_evacuation(self, alertes):
        """Déplace les récolteuses en DANGER vers des zones sûres."""
        ordres = evacuation_protocol(self.maps, self.mon_id, alertes)
        for ordre in ordres:
            if self.restantes() <= 1:
                break
            cmd = (f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}"
                   f"|{ordre['dest_y']}|{ordre['dest_x']}")
            if self.action_ok(cmd):
                self.maps['obj'][ordre['orig_y']][ordre['orig_x']] = 'X'
                self.maps['obj'][ordre['dest_y']][ordre['dest_x']] = str(self.mon_id)
                print(f"[RedHood]  Fuite ({ordre['orig_x']},{ordre['orig_y']})"
                      f" → ({ordre['dest_x']},{ordre['dest_y']})")

    # ----------------------------------------------------------
    #  Étape 4 : Placement de récolteuses
    # ----------------------------------------------------------

    def etape_recolteuses(self):
        """
        Place des récolteuses sur les meilleurs spots disponibles.
        On en pose autant que le budget et les actions permettent,
        en diversifiant les secteurs (max 3 par secteur par tour).
        """
        if self.epice < COUT_ACTION:
            return

        result         = find_best_locations(self.maps, top_n=50)
        spots          = result["top_spots"]
        poses_par_sec  = {0: 0, 1: 0, 2: 0, 3: 0}
        MAX_PAR_SECTEUR = 3

        for spot in spots:
            if self.restantes() <= 1 or self.epice < COUT_ACTION:
                break
            x, y = spot["coords"]
            if self.maps['obj'][y][x] != 'X':
                continue
            sec = spot["secteur"]
            if poses_par_sec[sec] >= MAX_PAR_SECTEUR:
                continue
            if self.action_ok(f"AJOUTERRECOLTEUSE|{y}|{x}"):
                self.maps['obj'][y][x] = str(self.mon_id)
                self.epice -= COUT_ACTION
                poses_par_sec[sec] += 1
                print(f"[RedHood]  Récolteuse en ({x},{y}) sect={sec}"
                      f" rendement={spot['rendement']}")

    # ----------------------------------------------------------
    #  Étape 5 : Usines
    # ----------------------------------------------------------

    def etape_usines(self):
        """
        Construit une usine si rentable et qu'on a ≥ 3 récolteuses.
        On peut en poser plusieurs par tour si le budget le permet.
        """
        if len(self.mes_recolteuses()) < 3:
            return

        for _ in range(2):  # au plus 2 usines par tour
            if self.restantes() <= 1 or self.epice < COUT_ACTION:
                break
            spot = find_best_factory_spot(self.maps, self.mon_id)
            if spot["coords"] is None or spot["score_rentabilite"] <= 0:
                break
            x, y = spot["coords"]
            if self.action_ok(f"AJOUTERUSINE|{y}|{x}"):
                self.maps['obj'][y][x] = 'U'
                self.epice -= COUT_ACTION
                print(f"[RedHood]  Usine en ({x},{y}) score={spot['score_rentabilite']}")

    # ----------------------------------------------------------
    #  Étape 6 : Sabotages
    # ----------------------------------------------------------

    def etape_sabotage(self):
        """
        Saboter stratégiquement si on est en position solide.
        Budget : on garde au moins 10 000 de marge pour les récolteuses.
        """
        if self.epice < COUT_ACTION * 3:
            return
        if len(self.mes_recolteuses()) < 3:
            return
        if not self.classement_ennemis:
            return

        cibles = strategic_sabotage_advance(self.maps, self.mon_id, self.classement_ennemis)
        for cible in cibles:
            if self.restantes() <= 1 or self.epice < COUT_ACTION:
                break
            sec = cible["secteur"]
            if sec in self.sabotages_tour:
                continue
            if self.action_ok(f"SABOTER|{sec}"):
                self.epice -= COUT_ACTION
                self.sabotages_tour.add(sec)
                print(f"[RedHood]  Sabotage sect={sec}"
                      f" score={cible['score_cible']:.1f}"
                      f" (leader_tué={cible['dont_leader']})")

    # ----------------------------------------------------------
    #  Boucle de jeu
    # ----------------------------------------------------------

    def play_turn(self, numero_tour):
        self.tour        = numero_tour
        self.nb_actions  = 0
        self.sabotages_tour = set()

        print(f"\n{'='*50}")
        print(f"  RedHood | Tour {numero_tour} | Joueur {self.mon_id}")
        print(f"{'='*50}")

        # Décrémenter les ornithoptères
        self.tick_ornithopteres()

        # 1. État du monde (actions 1 et 2)
        self.etape_recuperer_etat()
        print(f"  Épice={self.epice} | "
              f"Récolteuses={len(self.mes_recolteuses())} | "
              f"Actions restantes={self.restantes()}")

        # 2. Warnings vers (action 3 si nécessaire)
        alertes = self.etape_warnings()
        print(f"  Alertes vers : {alertes}")

        # 3. Ornithoptères (protège avant d'évacuer)
        self.etape_ornithopteres()

        # 4. Évacuation urgente
        self.etape_evacuation(alertes)

        # 5. Nouvelles récolteuses
        self.etape_recolteuses()

        # 6. Usines
        self.etape_usines()

        # 7. Sabotages
        self.etape_sabotage()

        # 8. Fin de tour (obligatoire — ne compte PAS dans le quota de 15)
        self.client.command("FINDETOUR")

        print(f"  → Actions utilisées ce tour : {self.nb_actions}/{MAX_ACTIONS}")

    def run(self):
        self.connect()
        while True:
            msg = self.client.recv_line(timeout=60)
            if not msg:
                print("[RedHood] Pas de message — fin de partie.")
                break
            if msg.startswith("DEBUT_TOUR"):
                try:
                    numero_tour = int(msg.split('|')[1])
                except (IndexError, ValueError):
                    numero_tour = self.tour + 1
                self.play_turn(numero_tour)
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