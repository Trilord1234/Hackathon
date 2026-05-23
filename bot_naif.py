import socket

HAUTEUR, LARGEUR = 16, 18

class BotNaif:
    def __init__(self):
        self.equipe = "Naif"
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
        """Pour DENSITE, ELEMENTS, WARNING, SCORES — réponse garantie."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self._readline()

    def envoyer_action(self, cmd):
        """Pour les actions — tente de lire OK/NOK avec timeout court."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        self.sock.settimeout(0.4)
        try:
            rep = self._readline()
            return rep
        except (socket.timeout, OSError):
            self._buffer = ""  # vider le buffer si timeout
            return None
        finally:
            self.sock.settimeout(None)

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

            rep_densite = self.envoyer_query("DENSITE")
            rep_elements = self.envoyer_query("ELEMENTS")
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
                rep = self.envoyer_action(f"AJOUTERRECOLTEUSE|{l}|{c}")
                actions -= 1
                if rep == "NOK":
                    break  # plus d'argent

            self.sock.sendall(("FINDETOUR\n").encode('utf-8'))
            print(f"[Naif] FINDETOUR envoyé")


if __name__ == "__main__":
    try:
        BotNaif().connecter()
    except (ConnectionResetError, ConnectionError) as e:
        print(f"[Naif] Déconnecté : {e}")
    except KeyboardInterrupt:
        pass
