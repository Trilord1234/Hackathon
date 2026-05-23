#!/usr/bin/env python3
# ============================================================
#  IA For The Spice  —  client TCP
# ============================================================
import socket
import time

from Maps import (
    maps, update_map, get_my_spice, classify_threats_scores,
    find_best_locations, find_best_factory_spot,
    strategic_sabotage_advance, evacuation_protocol,
    get_secteur_de_case, apply_bonus_factories, get_hex_neighbors
)

# -------- Configuration --------
HOST       = "127.0.0.1"
PORT       = 1234
TEAM_NAME  = "SpiceBot"   # < 15 caractères

# -------- Constantes -----------
COUT_ACTION   = 5000   # coût d'une récolteuse, usine ou sabotage
MAX_ACTIONS   = 15
ROWS, COLS    = 16, 18


# ==============================================================
#  Couche réseau
# ==============================================================

class GameClient:
    def __init__(self, host, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.buffer = ""

    def recv_line(self, timeout=4.5):
        """Lit une ligne complète depuis le serveur (bloquant avec timeout)."""
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
        # Retourne ce qu'on a même sans \n (cas fin de partie sans notification)
        line, self.buffer = self.buffer, ""
        return line.strip()

    def send(self, msg):
        """Envoie un message terminé par \n."""
        self.sock.sendall((msg + '\n').encode('utf-8'))

    def command(self, msg):
        """Envoie une commande et retourne la réponse du serveur."""
        self.send(msg)
        return self.recv_line()


# ==============================================================
#  Logique de l'IA
# ==============================================================

class SpiceAI:
    def __init__(self):
        self.client   = GameClient(HOST, PORT)
        self.mon_id   = None
        self.epice    = 0
        self.actions_restantes = MAX_ACTIONS
        self.tour     = 0

        # Mémoire du jeu
        self.maps     = maps          # partagé depuis Maps.py
        self.ornithopteres = {0: 0, 1: 0, 2: 0, 3: 0}  # tours restants par secteur
        self.sabotages_en_cours = set()                  # secteurs sabotés ce tour

    # ----------------------------------------------------------
    #  Connexion & identification
    # ----------------------------------------------------------

    def connect(self):
        msg = self.client.recv_line()
        if msg != "NOM_EQUIPE":
            raise RuntimeError(f"Message inattendu lors de la connexion : {msg}")
        rep = self.client.command(TEAM_NAME)
        # Réponse : "Bonjour SpiceBot vous êtes l'équipe |N"
        self.mon_id = str(rep.split('|')[-1].strip())
        print(f"[IA] Connecté en tant que joueur {self.mon_id}")

    # ----------------------------------------------------------
    #  Helpers : envoyer des commandes en tenant compte du quota
    # ----------------------------------------------------------

    def cmd(self, message):
        """Envoie une commande si le quota n'est pas épuisé. Retourne True si OK."""
        if self.actions_restantes <= 0:
            return False
        rep = self.client.command(message)
        self.actions_restantes -= 1
        return rep.startswith("OK")

    def demande(self, message):
        """Envoie une demande (compte dans le quota) et retourne la réponse brute."""
        if self.actions_restantes <= 0:
            return None
        rep = self.client.command(message)
        self.actions_restantes -= 1
        return rep

    # ----------------------------------------------------------
    #  Mise à jour de l'état du monde
    # ----------------------------------------------------------

    def refresh_state(self):
        """Récupère DENSITE, ELEMENTS et SCORES depuis le serveur."""
        dns_raw   = self.demande("DENSITE")
        if dns_raw:
            update_map("DENSITE", dns_raw, self.maps)

        elem_raw  = self.demande("ELEMENTS")
        if elem_raw:
            update_map("ELEMENTS", elem_raw, self.maps)

        scores_raw = self.demande("SCORES")
        if scores_raw:
            self.epice = get_my_spice(scores_raw, self.mon_id)
            self.classement_ennemis = classify_threats_scores(scores_raw, self.mon_id)
        else:
            self.classement_ennemis = []

        # Décrémente les ornithoptères actifs
        for sec in range(4):
            if self.ornithopteres[sec] > 0:
                self.ornithopteres[sec] -= 1

    def get_warnings(self):
        """Récupère les alertes de vers pour les secteurs surveillés."""
        raw = self.demande("WARNING")
        if not raw:
            return ['INCONNU'] * 4
        parts = raw.split('|')
        if len(parts) != 4:
            return ['INCONNU'] * 4
        return [p.strip() for p in parts]

    # ----------------------------------------------------------
    #  Comptage de nos récolteuses
    # ----------------------------------------------------------

    def mes_recolteuses(self):
        """Retourne la liste des (x, y) de nos récolteuses."""
        return [
            (x, y)
            for y in range(ROWS)
            for x in range(COLS)
            if self.maps['obj'][y][x] == str(self.mon_id)
        ]

    # ----------------------------------------------------------
    #  Phase 1 : Déploiement des ornithoptères
    # ----------------------------------------------------------

    def phase_ornithopteres(self):
        """
        Déploie un ornithoptère dans le meilleur secteur (celui qui contient
        le plus de nos récolteuses) si aucun n'est actif dans ce secteur.
        """
        if self.actions_restantes <= 0:
            return

        # Compte nos récolteuses par secteur
        count = {i: 0 for i in range(4)}
        for x, y in self.mes_recolteuses():
            count[get_secteur_de_case(x, y)] += 1

        # Déployer un orni dans les secteurs avec des récolteuses et sans surveillance
        for sec in sorted(count, key=lambda s: count[s], reverse=True):
            if count[sec] > 0 and self.ornithopteres[sec] == 0:
                if self.cmd(f"AJOUTERORNI|{sec}"):
                    self.ornithopteres[sec] = 5
                    print(f"[IA] Ornithoptère déployé dans le secteur {sec}")
                    break  # 1 seul par tour pour économiser les actions

    # ----------------------------------------------------------
    #  Phase 2 : Évacuation d'urgence
    # ----------------------------------------------------------

    def phase_evacuation(self, alertes):
        """Déplace les récolteuses menacées vers des zones sûres."""
        ordres = evacuation_protocol(self.maps, self.mon_id, alertes)
        for ordre in ordres:
            if self.actions_restantes <= 0:
                break
            cmd = f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}|{ordre['dest_y']}|{ordre['dest_x']}"
            if self.cmd(cmd):
                # Mise à jour locale de la carte
                self.maps['obj'][ordre['orig_y']][ordre['orig_x']] = 'X'
                self.maps['obj'][ordre['dest_y']][ordre['dest_x']] = str(self.mon_id)
                print(f"[IA] Évacuation ({ordre['orig_x']},{ordre['orig_y']}) → ({ordre['dest_x']},{ordre['dest_y']})")

    # ----------------------------------------------------------
    #  Phase 3 : Placement de récolteuses
    # ----------------------------------------------------------

    def phase_recolteuses(self):
        """
        Place des récolteuses sur les meilleurs emplacements disponibles,
        tant qu'on en a les moyens (5000 épice chacune).
        """
        if self.epice < COUT_ACTION or self.actions_restantes <= 0:
            return

        result = find_best_locations(self.maps, top_n=20)
        recolteuses_actuelles = len(self.mes_recolteuses())

        # Limite raisonnable : ne pas surcharger un seul secteur
        for spot in result["top_spots"]:
            if self.epice < COUT_ACTION or self.actions_restantes <= 0:
                break
            x, y = spot["coords"]
            # Vérifie que la case est toujours libre
            if self.maps['obj'][y][x] != 'X':
                continue
            if self.cmd(f"AJOUTERRECOLTEUSE|{y}|{x}"):
                self.maps['obj'][y][x] = str(self.mon_id)
                self.epice -= COUT_ACTION
                recolteuses_actuelles += 1
                print(f"[IA] Récolteuse placée en ({x},{y}) — rendement estimé {spot['rendement']}")
                # Une seule pose par tour les premiers tours pour étaler les risques
                if recolteuses_actuelles <= 2:
                    break

    # ----------------------------------------------------------
    #  Phase 4 : Construction d'usines
    # ----------------------------------------------------------

    def phase_usines(self):
        """Construit une usine si c'est rentable."""
        if self.epice < COUT_ACTION or self.actions_restantes <= 0:
            return
        # N'investir dans une usine que si on a déjà plusieurs récolteuses
        if len(self.mes_recolteuses()) < 3:
            return

        spot = find_best_factory_spot(self.maps, self.mon_id)
        if spot["coords"] is None or spot["score_rentabilite"] <= 0:
            return

        x, y = spot["coords"]
        if self.cmd(f"AJOUTERUSINE|{y}|{x}"):
            self.maps['obj'][y][x] = 'U'
            self.epice -= COUT_ACTION
            print(f"[IA] Usine construite en ({x},{y}) — score {spot['score_rentabilite']}")

    # ----------------------------------------------------------
    #  Phase 5 : Sabotage offensif
    # ----------------------------------------------------------

    def phase_sabotage(self):
        """
        Saboter le secteur le plus rentable si on peut se le permettre
        (≥ 2× le coût pour garder une marge pour les récolteuses).
        """
        if self.epice < COUT_ACTION * 2 or self.actions_restantes <= 0:
            return
        if not self.classement_ennemis:
            return
        # N'activer le sabotage que si on est en bonne position (≥ 3 récolteuses)
        if len(self.mes_recolteuses()) < 3:
            return

        cibles = strategic_sabotage_advance(self.maps, self.mon_id, self.classement_ennemis)
        for cible in cibles:
            sec = cible["secteur"]
            if sec in self.sabotages_en_cours:
                continue
            if self.cmd(f"SABOTER|{sec}"):
                self.epice -= COUT_ACTION
                self.sabotages_en_cours.add(sec)
                print(f"[IA] Sabotage du secteur {sec} (score={cible['score_cible']:.1f})")
            break  # Un sabotage par tour suffit généralement

    # ----------------------------------------------------------
    #  Boucle principale
    # ----------------------------------------------------------

    def play_turn(self, numero_tour):
        self.tour = numero_tour
        self.actions_restantes = MAX_ACTIONS
        self.sabotages_en_cours = set()

        print(f"\n=== Tour {numero_tour} | Joueur {self.mon_id} ===")

        # 1. Mettre à jour l'état du monde (3 demandes)
        self.refresh_state()
        print(f"    Épice : {self.epice} | Récolteuses : {len(self.mes_recolteuses())}")

        # 2. Récupérer les avertissements vers (1 demande si orni actif)
        alertes = ['INCONNU'] * 4
        if any(v > 0 for v in self.ornithopteres.values()):
            alertes = self.get_warnings()
        print(f"    Alertes : {alertes}")

        # 3. Déployer ornithoptères
        self.phase_ornithopteres()

        # 4. Évacuer les récolteuses en danger
        self.phase_evacuation(alertes)

        # 5. Placer des récolteuses
        self.phase_recolteuses()

        # 6. Construire des usines
        self.phase_usines()

        # 7. Saboter
        self.phase_sabotage()

        # 8. Fin de tour
        self.client.command("FINDETOUR")
        print(f"    Actions utilisées : {MAX_ACTIONS - self.actions_restantes}/{MAX_ACTIONS}")

    def run(self):
        self.connect()

        while True:
            msg = self.client.recv_line(timeout=30)
            if not msg:
                print("[IA] Pas de message reçu — fin de partie probable.")
                break

            if msg.startswith("DEBUT_TOUR"):
                try:
                    numero_tour = int(msg.split('|')[1])
                except (IndexError, ValueError):
                    numero_tour = self.tour + 1
                self.play_turn(numero_tour)
            else:
                print(f"[IA] Message inconnu : {msg!r}")


# ==============================================================
#  Point d'entrée
# ==============================================================

if __name__ == "__main__":
    ai = SpiceAI()
    try:
        ai.run()
    except KeyboardInterrupt:
        print("\n[IA] Arrêt manuel.")
    except Exception as e:
        print(f"[IA] Erreur fatale : {e}")
        raise
