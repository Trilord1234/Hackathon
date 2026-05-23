import socket
import sys

HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15

def get_secteur(l, c):
    if l <= 7:
        return 0 if c <= 8 else 1
    else:
        return 2 if c <= 8 else 3

def distance_rapide(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class SpiceBotUltime:
    def __init__(self, equipe="LesVersPythons"):
        self.equipe = equipe
        self.host = "127.0.0.1"
        self.port = 1234
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self.actions_restantes = MAX_ACTIONS
        self._buffer = ""

        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {
                    'densite': 0,
                    'element': 'X',
                    'secteur': get_secteur(l, c)
                }

    # ─────────────────────────────────────────────
    # COUCHE RÉSEAU
    # ─────────────────────────────────────────────

    def _readline(self):
        """Lit UNE ligne complète depuis le socket via buffer interne."""
        while '\n' not in self._buffer:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                raise ConnectionError("Serveur déconnecté.")
            self._buffer += data
        line, self._buffer = self._buffer.split('\n', 1)
        return line.strip()

    def envoyer(self, cmd):
        """Envoie une commande ET lit la réponse (OK/NOK ou données).
        À utiliser pour TOUT : queries ET actions.
        Le serveur répond toujours OK ou NOK selon le manuel."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        rep = self._readline()
        return rep

    def envoyer_action(self, cmd):
        """Wrapper qui appelle envoyer() et décrémente le compteur d'actions."""
        if self.actions_restantes > 0:
            rep = self.envoyer(cmd)
            self.actions_restantes -= 1
            return rep
        return None

    # ─────────────────────────────────────────────
    # CONNEXION & BOUCLE PRINCIPALE
    # ─────────────────────────────────────────────

    def connecter(self):
        print(f"[*] Connexion au serveur {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))

        msg = self._readline()
        if msg == "NOM_EQUIPE":
            self.sock.sendall((self.equipe + "\n").encode('utf-8'))
            reponse = self._readline()
            print(f"[*] Réponse serveur : {reponse}")
            if "|" in reponse:
                try:
                    self.mon_id = int(reponse.split('|')[1].strip())
                    print(f"[+] Mon ID de joueur : {self.mon_id}")
                except ValueError:
                    print("[!] Impossible de parser l'ID — brut :", reponse)

        self.boucle_jeu()

    def actualiser_plateau(self):
        rep_densite = self.envoyer("DENSITE")
        rep_elements = self.envoyer("ELEMENTS")
        self.actions_restantes -= 2  # comptabilise les 2 queries

        if len(rep_densite) >= HAUTEUR * LARGEUR and len(rep_elements) >= HAUTEUR * LARGEUR:
            for i in range(HAUTEUR * LARGEUR):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                self.plateau[(l, c)]['element'] = rep_elements[i]

    def obtenir_cases_par_element(self, element_type):
        return [
            (l, c)
            for (l, c), data in self.plateau.items()
            if data['element'] == str(element_type)
        ]

    def boucle_jeu(self):
        print("[*] En attente du début de la partie (appuyez sur ENTRÉE dans le jeu)...")
        while True:
            msg = self._readline()
            if not msg:
                continue

            if not msg.startswith("DEBUT_TOUR"):
                print(f"[~] Message ignoré : {msg}")
                continue

            parts = msg.split('|')
            tour = parts[1] if len(parts) > 1 else "?"
            print(f"\n{'='*10} TOUR {tour} {'='*10}")
            self.actions_restantes = MAX_ACTIONS

            self.actualiser_plateau()
            alertes_vers = self.envoyer("WARNING").split('|')
            self.actions_restantes -= 1  # comptabilise WARNING
            print(f"[*] Alertes Vers : {alertes_vers}")
            # Il reste MAX_ACTIONS - 3 = 12 actions réelles

            self.jouer_tour(alertes_vers)

            print(f"[*] Fin du tour. Actions restantes : {self.actions_restantes}")
            self.envoyer("FINDETOUR")

    # ─────────────────────────────────────────────
    # CERVEAU : STRATÉGIE IMITATEUR
    # ─────────────────────────────────────────────

    def jouer_tour(self, alertes_vers):
        mes_recolteuses = self.obtenir_cases_par_element(self.mon_id)
        ennemis = []
        for i in range(4):
            if i != self.mon_id:
                ennemis.extend(self.obtenir_cases_par_element(i))

        # ── PRIORITÉ 1 : SURVIE ──────────────────
        for l, c in mes_recolteuses:
            if self.actions_restantes <= 0:
                break
            secteur = get_secteur(l, c)
            if alertes_vers[secteur] == "DANGER":
                print(f"  [!] DANGER S{secteur} ! Évacuation ({l},{c})")
                for (nl, nc), data in self.plateau.items():
                    if data['element'] == 'X' and alertes_vers[data['secteur']] != "DANGER":
                        self.envoyer_action(f"DEPLACER|{l}|{c}|{nl}|{nc}")
                        break

        # ── PRIORITÉ 2 : RADARS (ORNI) ───────────
        secteurs_occupes = {get_secteur(l, c) for l, c in mes_recolteuses}
        for s in secteurs_occupes:
            if self.actions_restantes <= 0:
                break
            if alertes_vers[s] == "INCONNU":
                print(f"  [Radar] Orni secteur {s}")
                self.envoyer_action(f"AJOUTERORNI|{s}")

        # ── PRIORITÉ 3 : RIPOSTE (Tit-for-Tat) ──
        for l, c in mes_recolteuses:
            if self.actions_restantes <= 0:
                break
            for el, ec in ennemis:
                if distance_rapide(l, c, el, ec) <= 2:
                    print(f"  [Riposte] Ennemi en ({el},{ec}) — blocage !")
                    meilleure_riposte, max_d = None, -1
                    for dl, dc in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
                        rl, rc = el + dl, ec + dc
                        if (rl, rc) in self.plateau and self.plateau[(rl, rc)]['element'] == 'X':
                            if self.plateau[(rl, rc)]['densite'] > max_d:
                                max_d = self.plateau[(rl, rc)]['densite']
                                meilleure_riposte = (rl, rc)
                    if meilleure_riposte:
                        self.envoyer_action(
                            f"DEPLACER|{l}|{c}|{meilleure_riposte[0]}|{meilleure_riposte[1]}"
                        )

        # ── PRIORITÉ 4 : EXPANSION (Farming) ─────
        cases_libres = [
            (l, c)
            for (l, c), data in self.plateau.items()
            if data['element'] == 'X' and alertes_vers[data['secteur']] != "DANGER"
        ]
        cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)

        for l, c in cases_libres:
            if self.actions_restantes <= 0:
                break
            if not any(distance_rapide(l, c, el, ec) <= 2 for el, ec in ennemis):
                print(f"  [Farming] Récolteuse ({l},{c}) densité={self.plateau[(l,c)]['densite']}")
                rep = self.envoyer_action(f"AJOUTERRECOLTEUSE|{l}|{c}")
                if rep == "NOK":
                    # Plus d'argent — arrêter les achats
                    print("  [!] NOK reçu — plus d'argent, stop farming")
                    break


if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "Bot_Ultime"
    bot = SpiceBotUltime(equipe=nom_equipe)
    try:
        bot.connecter()
    except ConnectionResetError:
        print("\n[!] Serveur déconnecté (fin de partie ou kick).")
    except ConnectionError as e:
        print(f"\n[!] Connexion perdue : {e}")
    except KeyboardInterrupt:
        print("\n[!] Arrêt du bot.")
    except Exception as e:
        print(f"[X] Erreur critique : {e}")
        import traceback; traceback.print_exc()
