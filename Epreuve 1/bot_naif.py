import socket
import select
import sys

HAUTEUR, LARGEUR = 16, 18
PRIX_RECOLTEUSE = 5000

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

    def envoyer(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def lire_reseau(self, timeout=0.05):
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if ready:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                sys.exit()
            self._buffer += data

        lignes = []
        while '\n' in self._buffer:
            ligne, self._buffer = self._buffer.split('\n', 1)
            lignes.append(ligne.strip())
        return [l for l in lignes if l]

    def requete(self, cmd):
        self.envoyer(cmd)
        while True:
            for msg in self.lire_reseau(timeout=0.02):
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288:
                    return msg
                elif cmd in ["WARNING", "SCORES"] and "|" in msg and "DEBUT_TOUR" not in msg:
                    return msg

    def connecter(self):
        self.sock.connect(("127.0.0.1", 1234))
        while True:
            for msg in self.lire_reseau(timeout=0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    self.mon_id = int(msg.split('|')[1])
                    self.boucle()
                    return

    def boucle(self):
        while True:
            for msg in self.lire_reseau(timeout=0.1):
                if msg.startswith("DEBUT_TOUR"):
                    tour = msg.split('|')[1]
                    print(f"[Naif] === Tour {tour} ===")
                    
                    rep_densite = self.requete("DENSITE")
                    rep_elements = self.requete("ELEMENTS")
                    scores_bruts = self.requete("SCORES").split('|')
                    
                    try: mon_budget = int(scores_bruts[self.mon_id])
                    except: mon_budget = 0
                    
                    for i in range(HAUTEUR * LARGEUR):
                        l, c = divmod(i, LARGEUR)
                        self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                        self.plateau[(l, c)]['element'] = rep_elements[i]
                    
                    actions = 11
                    cases_libres = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'X']
                    cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)
                    
                    for l, c in cases_libres:
                        if actions <= 0 or mon_budget < PRIX_RECOLTEUSE: break
                        self.envoyer(f"AJOUTERRECOLTEUSE|{l}|{c}")
                        actions -= 1
                        mon_budget -= PRIX_RECOLTEUSE
                    
                    self.envoyer("FINDETOUR")

if __name__ == "__main__":
    BotNaif().connecter()