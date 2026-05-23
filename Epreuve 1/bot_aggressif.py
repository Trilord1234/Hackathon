import socket
import select
import sys

HAUTEUR, LARGEUR = 16, 18
PRIX_RECOLTEUSE = 5000

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

    def envoyer(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def lire_reseau(self, timeout=0.05):
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if ready:
            data = self.sock.recv(4096).decode('utf-8')
            if not data: sys.exit()
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
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288: return msg
                elif cmd in ["WARNING", "SCORES"] and "|" in msg and "DEBUT_TOUR" not in msg: return msg

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
                    print(f"[Agressif] === Tour {tour} ===")
                    
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
                    mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
                    ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
                    
                    if not mes_unites and mon_budget >= PRIX_RECOLTEUSE and actions > 0:
                        self.envoyer("AJOUTERRECOLTEUSE|8|9")
                        actions -= 1
                    elif mes_unites and ennemis:
                        cible_l, cible_c = ennemis[0]
                        for ml, mc in mes_unites:
                            if actions <= 0: break
                            for dl, dc in [(-1,0), (1,0), (0,-1), (0,1), (-1,-1), (1,1)]:
                                nl, nc = cible_l + dl, cible_c + dc
                                if (nl, nc) in self.plateau and self.plateau[(nl, nc)]['element'] == 'X':
                                    self.envoyer(f"DEPLACER|{ml}|{mc}|{nl}|{nc}")
                                    actions -= 1
                                    break
                    
                    self.envoyer("FINDETOUR")

if __name__ == "__main__":
    BotAgressif().connecter()