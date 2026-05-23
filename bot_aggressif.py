import socket

HAUTEUR, LARGEUR = 16, 18

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class BotAgressif:
    def __init__(self):
        self.equipe = "Bot_Agressif"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X'}

    def _readline(self):
        while '\n' not in self._buffer:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                raise ConnectionError("Serveur déconnecté.")
            self._buffer += data
        line, self._buffer = self._buffer.split('\n', 1)
        return line.strip()

    def envoyer_query(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self._readline()

    def envoyer_action(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        self.sock.settimeout(0.4)
        try:
            rep = self._readline()
            return rep
        except (socket.timeout, OSError):
            self._buffer = ""
            return None
        finally:
            self.sock.settimeout(None)

    def connecter(self):
        self.sock.connect(("127.0.0.1", 1234))
        msg = self._readline()
        if msg == "NOM_EQUIPE":
            self.sock.sendall((self.equipe + "\n").encode('utf-8'))
            rep = self._readline()
            print(f"[Agressif] Connecté : {rep}")
            if "|" in rep:
                try:
                    self.mon_id = int(rep.split('|')[1].strip())
                except ValueError:
                    pass
        self.boucle()

    def boucle(self):
        print("[Agressif] En attente...")
        while True:
            msg = self._readline()
            if not msg or not msg.startswith("DEBUT_TOUR"):
                continue

            tour = msg.split('|')[1] if '|' in msg else "?"
            print(f"[Agressif] === Tour {tour} ===")

            rep_densite = self.envoyer_query("DENSITE")
            rep_elements = self.envoyer_query("ELEMENTS")
            for i in range(HAUTEUR * LARGEUR):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                self.plateau[(l, c)]['element'] = rep_elements[i]

            actions = 13
            mes_unites = [(l,c) for (l,c),d in self.plateau.items() if d['element'] == str(self.mon_id)]
            ennemis    = [(l,c) for (l,c),d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]

            if not mes_unites and actions > 0:
                self.envoyer_action("AJOUTERRECOLTEUSE|8|9")
                actions -= 1
            elif mes_unites and ennemis:
                cible_l, cible_c = ennemis[0]
                for ml, mc in mes_unites:
                    if actions <= 0: break
                    for dl, dc in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]:
                        nl, nc = cible_l+dl, cible_c+dc
                        if (nl,nc) in self.plateau and self.plateau[(nl,nc)]['element'] == 'X':
                            self.envoyer_action(f"DEPLACER|{ml}|{mc}|{nl}|{nc}")
                            actions -= 1
                            break
            else:
                cases = sorted(
                    [(l,c) for (l,c),d in self.plateau.items() if d['element']=='X'],
                    key=lambda xy: self.plateau[xy]['densite'], reverse=True
                )
                for l,c in cases:
                    if actions <= 0: break
                    rep = self.envoyer_action(f"AJOUTERRECOLTEUSE|{l}|{c}")
                    actions -= 1
                    if rep == "NOK": break

            self.sock.sendall(("FINDETOUR\n").encode('utf-8'))
            print("[Agressif] FINDETOUR envoyé")


if __name__ == "__main__":
    try:
        BotAgressif().connecter()
    except (ConnectionResetError, ConnectionError) as e:
        print(f"[Agressif] Déconnecté : {e}")
    except KeyboardInterrupt:
        pass
