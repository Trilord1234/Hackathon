import socket
import time

HAUTEUR, LARGEUR = 16, 18

class BotNaif:
    def __init__(self):
        self.equipe = "Bot_Naif"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X'}

    def envoyer(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self.sock.recv(4096).decode('utf-8').strip()

    def connecter(self):
        self.sock.connect(("127.0.0.1", 1234))
        if self.sock.recv(1024).decode('utf-8').strip() == "NOM_EQUIPE":
            rep = self.envoyer(self.equipe)
            if "|" in rep: self.mon_id = int(rep.split('|')[1])
        self.boucle()

    def boucle(self):
        while True:
            msg = self.sock.recv(1024).decode('utf-8').strip()
            if not msg: continue
            if msg.startswith("DEBUT_TOUR"):
                rep_densite = self.envoyer("DENSITE")
                rep_elements = self.envoyer("ELEMENTS")
                for i in range(HAUTEUR * LARGEUR):
                    l, c = divmod(i, LARGEUR)
                    self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                    self.plateau[(l, c)]['element'] = rep_elements[i]
                
                # --- CERVEAU NAÏF ---
                actions = 15
                # Cherche les cases libres triées par densité d'épice
                cases_libres = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'X']
                cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)
                
                for l, c in cases_libres:
                    if actions <= 0: break
                    self.envoyer(f"AJOUTERRECOLTEUSE|{l}|{c}")
                    actions -= 1
                
                self.envoyer("FINDETOUR")

if __name__ == "__main__":
    BotNaif().connecter()