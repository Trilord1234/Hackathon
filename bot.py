import socket
import sys

HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15

def get_secteur(l, c):
    return (0 if c <= 8 else 1) if l <= 7 else (2 if c <= 8 else 3)

def dist(l1, c1, l2, c2):
    return max(abs(l1-l2), abs(c1-c2))

class SpiceBotUltime:
    def __init__(self, equipe="LesVersPythons"):
        self.equipe = equipe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self.actions_restantes = MAX_ACTIONS
        self._buffer = ""
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l,c)] = {'densite':0,'element':'X','secteur':get_secteur(l,c)}

    # ── RÉSEAU ────────────────────────────────────

    def _readline(self):
        """Lecture bloquante d'une ligne complète (boucle principale)."""
        while '\n' not in self._buffer:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                raise ConnectionError("Serveur déconnecté.")
            self._buffer += data
        line, self._buffer = self._buffer.split('\n', 1)
        return line.strip()

    def envoyer_query(self, cmd):
        """Queries seulement (DENSITE, ELEMENTS, WARNING) — réponse garantie."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        self.actions_restantes -= 1
        return self._readline()

    def envoyer_action(self, cmd):
        """Actions de jeu — tente de lire OK/NOK avec timeout court.
        Si le serveur ne répond pas dans 0.4s → on continue sans bloquer."""
        if self.actions_restantes <= 0:
            return None
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        self.actions_restantes -= 1
        self.sock.settimeout(0.4)
        try:
            rep = self._readline()
            return rep
        except (socket.timeout, OSError):
            self._buffer = ""  # vider résidus éventuels
            return None
        finally:
            self.sock.settimeout(None)  # toujours remettre en bloquant

    # ── CONNEXION ─────────────────────────────────

    def connecter(self):
        print(f"[*] Connexion à 127.0.0.1:1234...")
        self.sock.connect(("127.0.0.1", 1234))
        msg = self._readline()
        if msg == "NOM_EQUIPE":
            self.sock.sendall((self.equipe + "\n").encode('utf-8'))
            rep = self._readline()
            print(f"[*] Serveur : {rep}")
            if "|" in rep:
                try:
                    self.mon_id = int(rep.split('|')[1].strip())
                    print(f"[+] ID joueur : {self.mon_id}")
                except ValueError:
                    print("[!] Parse ID échoué, brut :", rep)
        self.boucle_jeu()

    # ── BOUCLE PRINCIPALE ─────────────────────────

    def boucle_jeu(self):
        print("[*] En attente de DEBUT_TOUR...")
        while True:
            msg = self._readline()
            if not msg:
                continue
            if not msg.startswith("DEBUT_TOUR"):
                print(f"[~] Ignoré : {msg!r}")
                continue

            tour = msg.split('|')[1] if '|' in msg else "?"
            print(f"\n{'='*12} TOUR {tour} {'='*12}")
            self.actions_restantes = MAX_ACTIONS

            # 3 queries = 3 actions consommées
            densite  = self.envoyer_query("DENSITE")
            elements = self.envoyer_query("ELEMENTS")
            alertes  = self.envoyer_query("WARNING").split('|')
            print(f"[*] WARNING : {alertes}  — actions restantes : {self.actions_restantes}")

            for i in range(HAUTEUR * LARGEUR):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l,c)]['densite'] = int(densite[i])
                self.plateau[(l,c)]['element'] = elements[i]

            self.jouer_tour(alertes)

            print(f"[*] Fin tour. Actions restantes : {self.actions_restantes}")
            # FINDETOUR : pas de réponse — sendall direct
            self.sock.sendall(("FINDETOUR\n").encode('utf-8'))
            print("[*] FINDETOUR envoyé → attente DEBUT_TOUR suivant\n")

    # ── STRATÉGIE ─────────────────────────────────

    def cases_de(self, element):
        return [(l,c) for (l,c),d in self.plateau.items() if d['element']==str(element)]

    def jouer_tour(self, alertes):
        mes = self.cases_de(self.mon_id)
        ennemis = []
        for i in range(4):
            if i != self.mon_id:
                ennemis.extend(self.cases_de(i))

        # PRIORITÉ 1 : Survie — fuir les vers
        for l,c in mes:
            if self.actions_restantes <= 0: break
            if alertes[get_secteur(l,c)] == "DANGER":
                print(f"  [!] DANGER ({l},{c}) — évacuation")
                for (nl,nc),d in self.plateau.items():
                    if d['element']=='X' and alertes[d['secteur']]!="DANGER":
                        self.envoyer_action(f"DEPLACER|{l}|{c}|{nl}|{nc}")
                        break

        # PRIORITÉ 2 : Radar — orni sur secteurs occupés inconnus
        for s in {get_secteur(l,c) for l,c in mes}:
            if self.actions_restantes <= 0: break
            if alertes[s] == "INCONNU":
                print(f"  [Radar] AJOUTERORNI secteur {s}")
                self.envoyer_action(f"AJOUTERORNI|{s}")

        # PRIORITÉ 3 : Riposte — bloquer les ennemis proches
        for l,c in mes:
            if self.actions_restantes <= 0: break
            for el,ec in ennemis:
                if dist(l,c,el,ec) <= 2:
                    print(f"  [Riposte] Ennemi ({el},{ec})")
                    best, best_d = None, -1
                    for dl,dc in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
                        rl,rc = el+dl, ec+dc
                        if (rl,rc) in self.plateau and self.plateau[(rl,rc)]['element']=='X':
                            if self.plateau[(rl,rc)]['densite'] > best_d:
                                best_d = self.plateau[(rl,rc)]['densite']
                                best = (rl,rc)
                    if best:
                        self.envoyer_action(f"DEPLACER|{l}|{c}|{best[0]}|{best[1]}")

        # PRIORITÉ 4 : Expansion — placer récolteuses sur cases denses sûres
        cases_libres = sorted(
            [(l,c) for (l,c),d in self.plateau.items()
             if d['element']=='X' and alertes[d['secteur']]!="DANGER"],
            key=lambda xy: self.plateau[xy]['densite'], reverse=True
        )
        for l,c in cases_libres:
            if self.actions_restantes <= 0: break
            if not any(dist(l,c,el,ec)<=2 for el,ec in ennemis):
                print(f"  [Farm] ({l},{c}) densité={self.plateau[(l,c)]['densite']}")
                rep = self.envoyer_action(f"AJOUTERRECOLTEUSE|{l}|{c}")
                if rep == "NOK":
                    print("  [!] NOK — plus d'argent")
                    break


if __name__ == "__main__":
    nom = sys.argv[1] if len(sys.argv) > 1 else "Bot_Ultime"
    bot = SpiceBotUltime(equipe=nom)
    try:
        bot.connecter()
    except ConnectionResetError:
        print("\n[!] Serveur déconnecté (fin de partie).")
    except ConnectionError as e:
        print(f"\n[!] Connexion perdue : {e}")
    except KeyboardInterrupt:
        print("\n[!] Arrêt.")
    except Exception as e:
        import traceback
        print(f"[X] Erreur : {e}")
        traceback.print_exc()
