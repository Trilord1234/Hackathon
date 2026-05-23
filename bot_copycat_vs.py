import socket

HAUTEUR, LARGEUR = 16, 18

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class BotCopycat:
    def __init__(self):
        self.equipe = "Bot_Copycat"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                secteur = 0 if l<=7 and c<=8 else 1 if l<=7 else 2 if c<=8 else 3
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': secteur}

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
                alertes_vers = self.envoyer("WARNING").split('|')
                
                for i in range(HAUTEUR * LARGEUR):
                    l, c = divmod(i, LARGEUR)
                    self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                    self.plateau[(l, c)]['element'] = rep_elements[i]
                
                actions = 15
                mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
                ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
                
                # 1. Esquive
                for l, c in mes_unites:
                    secteur = self.plateau[(l, c)]['secteur']
                    if alertes_vers[secteur] == "DANGER" and actions > 0:
                        for (nl, nc), d in self.plateau.items():
                            if d['element'] == 'X' and alertes_vers[d['secteur']] != "DANGER":
                                self.envoyer_sans_reponse(f"DEPLACER|{l}|{c}|{nl}|{nc}") # CORRIGÉ
                                actions -= 1
                                break

                # 2. Riposte
                for l, c in mes_unites:
                    for el, ec in ennemis:
                        if distance(l, c, el, ec) <= 2 and actions > 0:
                            for dl, dc in [(-1,0), (1,0), (0,-1), (0,1)]:
                                rl, rc = el+dl, ec+dc
                                if (rl, rc) in self.plateau and self.plateau[(rl, rc)]['element'] == 'X':
                                    self.envoyer_sans_reponse(f"DEPLACER|{l}|{c}|{rl}|{rc}") # CORRIGÉ
                                    actions -= 1
                                    break

                # 3. Expansion
                cases_libres = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'X' and alertes_vers[d['secteur']] != "DANGER"]
                cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)
                
                for l, c in cases_libres:
                    if actions <= 0: break
                    if not any(distance(l, c, el, ec) <= 2 for el, ec in ennemis):
                        self.envoyer_sans_reponse(f"AJOUTERRECOLTEUSE|{l}|{c}") # CORRIGÉ
                        actions -= 1
                
                self.envoyer_sans_reponse("FINDETOUR") # CORRIGÉ

if __name__ == "__main__":
    BotCopycat().connecter()