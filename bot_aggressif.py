import socket

HAUTEUR, LARGEUR = 16, 18

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

    def envoyer(self, cmd):
        """Envoie et LIT la réponse — vide toujours le tuyau TCP."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self._readline()

    def envoyer_sans_reponse(self, cmd):
        """Sans lecture — UNIQUEMENT pour FINDETOUR."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def connecter(self):
        self.sock.connect(("127.0.0.1", 1234))
        msg = self._readline()
        if msg == "NOM_EQUIPE":
            rep = self.envoyer(self.equipe)
            print(f"[Agressif] Connecté : {rep}")
            if "|" in rep:
                try:
                    self.mon_id = int(rep.split('|')[1].strip())
                except ValueError:
                    pass
        self.boucle()

    def boucle(self):
        print("[Agressif] En attente du début de la partie...")
        while True:
            msg = self._readline()
            if not msg:
                continue

            if msg.startswith("DEBUT_TOUR"):
                tour = msg.split('|')[1] if '|' in msg else "?"
                print(f"[Agressif] === Tour {tour} ===")

                rep_densite = self.envoyer("DENSITE")
                rep_elements = self.envoyer("ELEMENTS")
                for i in range(HAUTEUR * LARGEUR):
                    l, c = divmod(i, LARGEUR)
                    self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                    self.plateau[(l, c)]['element'] = rep_elements[i]

                # ── CERVEAU AGRESSIF ───────────────────────────────────────────
                actions = 15
                mes_unites = [
                    (l, c)
                    for (l, c), d in self.plateau.items()
                    if d['element'] == str(self.mon_id)
                ]
                ennemis = [
                    (l, c)
                    for (l, c), d in self.plateau.items()
                    if d['element'] in ['0','1','2','3']
                    and d['element'] != str(self.mon_id)
                ]

                if not mes_unites and actions > 0:
                    # Spawn au centre de la carte
                    self.envoyer(f"AJOUTERRECOLTEUSE|8|9")
                    actions -= 1

                elif mes_unites and ennemis:
                    cible_l, cible_c = ennemis[0]
                    mouvements = [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)]

                    for ml, mc in mes_unites:
                        if actions <= 0:
                            break
                        for dl, dc in mouvements:
                            nl, nc = cible_l + dl, cible_c + dc
                            if (nl, nc) in self.plateau and self.plateau[(nl, nc)]['element'] == 'X':
                                self.envoyer(f"DEPLACER|{ml}|{mc}|{nl}|{nc}")
                                actions -= 1
                                break

                elif mes_unites and not ennemis:
                    # Aucune cible : farm comme le naïf
                    cases_libres = [
                        (l, c)
                        for (l, c), d in self.plateau.items()
                        if d['element'] == 'X'
                    ]
                    cases_libres.sort(
                        key=lambda coord: self.plateau[coord]['densite'],
                        reverse=True
                    )
                    for l, c in cases_libres:
                        if actions <= 0:
                            break
                        self.envoyer(f"AJOUTERRECOLTEUSE|{l}|{c}")
                        actions -= 1

                self.envoyer_sans_reponse("FINDETOUR")


if __name__ == "__main__":
    BotAgressif().connecter()