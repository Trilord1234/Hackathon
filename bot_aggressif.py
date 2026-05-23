import socket

HAUTEUR, LARGEUR = 16, 18

class BotAgressif:
    def __init__(self):
        self.equipe = "Bot_Agressif"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X'}

    def envoyer(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self.sock.recv(4096).decode('utf-8').strip()

    def envoyer_sans_reponse(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))

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
                
                actions = 15
                mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
                ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
                
                if not mes_unites and actions > 0:
                    self.envoyer_sans_reponse("AJOUTERRECOLTEUSE|8|9") # CORRIGÉ
                    actions -= 1
                elif mes_unites and ennemis:
                    cible_l, cible_c = ennemis[0]
                    for ml, mc in mes_unites:
                        if actions <= 0: break
                        mouvements = [(-1,0), (1,0), (0,-1), (0,1), (-1,-1), (1,1)]
                        for dl, dc in mouvements:
                            nl, nc = cible_l + dl, cible_c + dc
                            if (nl, nc) in self.plateau and self.plateau[(nl, nc)]['element'] == 'X':
                                self.envoyer_sans_reponse(f"DEPLACER|{ml}|{mc}|{nl}|{nc}") # CORRIGÉ
                                actions -= 1
                                break
                
                self.envoyer_sans_reponse("FINDETOUR") # CORRIGÉ

if __name__ == "__main__":
    BotAgressif().connecter()