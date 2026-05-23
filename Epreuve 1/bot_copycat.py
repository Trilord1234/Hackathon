import socket
import select
import sys

HAUTEUR, LARGEUR = 16, 18
PRIX_RECOLTEUSE = 5000

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class BotCopycat:
    def __init__(self):
        self.equipe = "Bot_Copycat"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                secteur = 0 if l<=7 and c<=8 else 1 if l<=7 else 2 if c<=8 else 3
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': secteur}

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
                    print(f"[Copycat] === Tour {tour} ===")
                    
                    rep_densite = self.requete("DENSITE")
                    rep_elements = self.requete("ELEMENTS")
                    alertes_vers = self.requete("WARNING").split('|')
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
                    
                    # 1. Esquive
                    for l, c in mes_unites:
                        secteur = self.plateau[(l, c)]['secteur']
                        if alertes_vers[secteur] == "DANGER" and actions > 0:
                            for (nl, nc), d in self.plateau.items():
                                if d['element'] == 'X' and alertes_vers[d['secteur']] != "DANGER":
                                    self.envoyer(f"DEPLACER|{l}|{c}|{nl}|{nc}")
                                    actions -= 1
                                    break

                    # 2. Riposte
                    for l, c in mes_unites:
                        for el, ec in ennemis:
                            if distance(l, c, el, ec) <= 2 and actions > 0:
                                for dl, dc in [(-1,0), (1,0), (0,-1), (0,1)]:
                                    rl, rc = el+dl, ec+dc
                                    if (rl, rc) in self.plateau and self.plateau[(rl, rc)]['element'] == 'X':
                                        self.envoyer(f"DEPLACER|{l}|{c}|{rl}|{rc}")
                                        actions -= 1
                                        break

                    # 3. Expansion
                    cases_libres = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'X' and alertes_vers[d['secteur']] != "DANGER"]
                    cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)
                    
                    for l, c in cases_libres:
                        if actions <= 0 or mon_budget < PRIX_RECOLTEUSE: break
                        if not any(distance(l, c, el, ec) <= 2 for el, ec in ennemis):
                            self.envoyer(f"AJOUTERRECOLTEUSE|{l}|{c}")
                            actions -= 1
                            mon_budget -= PRIX_RECOLTEUSE
                    
                    self.envoyer("FINDETOUR")

if __name__ == "__main__":
    BotCopycat().connecter()