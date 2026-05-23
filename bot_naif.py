import socket

HAUTEUR, LARGEUR = 16, 18

class BotNaif:
    def __init__(self):
        self.equipe = "Bot_Naif"
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

    def envoyer(self, cmd):
        """Envoie une commande et lit la réponse (OK/NOK ou données)."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self._readline()

    def connecter(self):
        self.sock.connect(("127.0.0.1", 1234))
        msg = self._readline()
        if msg == "NOM_EQUIPE":
            self.sock.sendall((self.equipe + "\n").encode('utf-8'))
            rep = self._readline()
            print(f"[Naif] Connecté : {rep}")
            if "|" in rep:
                try:
                    self.mon_id = int(rep.split('|')[1].strip())
                except ValueError:
                    pass
        self.boucle()

    def boucle(self):
        print("[Naif] En attente...")
        while True:
            msg = self._readline()
            if not msg or not msg.startswith("DEBUT_TOUR"):
                continue

            tour = msg.split('|')[1] if '|' in msg else "?"
            print(f"[Naif] === Tour {tour} ===")

            # 2 queries utilisées sur les 15
            rep_densite = self.envoyer("DENSITE")
            rep_elements = self.envoyer("ELEMENTS")
            for i in range(HAUTEUR * LARGEUR):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                self.plateau[(l, c)]['element'] = rep_elements[i]

            actions = 13  # 15 - 2 queries
            cases_libres = [
                (l, c) for (l, c), d in self.plateau.items() if d['element'] == 'X'
            ]
            cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)

            for l, c in cases_libres:
                if actions <= 0:
                    break
                rep = self.envoyer(f"AJOUTERRECOLTEUSE|{l}|{c}")
                actions -= 1
                if rep == "NOK":
                    break  # plus d'argent

            self.envoyer("FINDETOUR")


if __name__ == "__main__":
    try:
        BotNaif().connecter()
    except ConnectionResetError:
        print("[Naif] Déconnecté (fin de partie).")
    except ConnectionError as e:
        print(f"[Naif] Connexion perdue : {e}")
    except KeyboardInterrupt:
        pass
