import socket
import select
import sys

HAUTEUR, LARGEUR = 16, 18

class BotRobuste:
    def __init__(self, equipe="Equipe_Alpha"):
        self.equipe = equipe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.plateau = {}

    def connecter(self):
        self.sock.connect(("127.0.0.1", 1234))
        print("[*] Connecté. En attente d'identification...")
        while True:
            for msg in self.lire_reseau(timeout=0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    self.mon_id = int(msg.split('|')[1])
                    print(f"[+] ID Joueur : {self.mon_id}")
                    self.boucle_jeu()
                    return

    def envoyer(self, cmd):
        """Envoie une commande brute au serveur."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def lire_reseau(self, timeout=0.1):
        """Lecture TCP parfaite : ne bloque pas, ne perd aucune donnée."""
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if ready:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                print("[!] Le serveur a coupé la connexion.")
                sys.exit()
            self._buffer += data

        lignes = []
        while '\n' in self._buffer:
            ligne, self._buffer = self._buffer.split('\n', 1)
            lignes.append(ligne.strip())
        return [l for l in lignes if l]

    def requete(self, cmd):
        """Envoie une demande (DENSITE, etc) et filtre intelligemment la réponse."""
        self.envoyer(cmd)
        while True:
            for msg in self.lire_reseau(timeout=0.1):
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288:
                    return msg
                elif cmd in ["WARNING", "SCORES"] and "|" in msg and "DEBUT_TOUR" not in msg:
                    return msg
                # S'il reçoit autre chose (une erreur FTS_...), il l'affiche au lieu de planter
                print(f"[Alerte Serveur] {msg}")

    def boucle_jeu(self):
        print("[*] Prêt. Lancez la partie depuis le jeu !")
        while True:
            for msg in self.lire_reseau(timeout=0.5):
                if msg.startswith("DEBUT_TOUR"):
                    tour = msg.split('|')[1]
                    print(f"\n{'='*15} TOUR {tour} {'='*15}")
                    self.jouer_tour()
                else:
                    print(f"[Message asynchrone reçu] {msg}")

    def jouer_tour(self):
        # 1. État des lieux
        densite = self.requete("DENSITE")
        elements = self.requete("ELEMENTS")
        warning = self.requete("WARNING")
        scores = self.requete("SCORES") # <-- TRÈS IMPORTANT POUR L'ÉCONOMIE

        print(f"[*] Argent et Scores : {scores}")
        print(f"[*] Dangers : {warning}")

        # 2. Action unique pour tester
        print("[*] Achat d'UNE SEULE récolteuse pour éviter le bug FTS_PasAssezDEpice...")
        max_d, meilleure_case = -1, None
        for i in range(HAUTEUR * LARGEUR):
            if elements[i] == 'X' and int(densite[i]) > max_d:
                max_d = int(densite[i])
                meilleure_case = divmod(i, LARGEUR)

        if meilleure_case:
            self.envoyer(f"AJOUTERRECOLTEUSE|{meilleure_case[0]}|{meilleure_case[1]}")
            
        # 3. Fin du tour propre
        print("[*] FINDETOUR envoyé.")
        self.envoyer("FINDETOUR")


if __name__ == "__main__":
    nom_bot = sys.argv[1] if len(sys.argv) > 1 else "EquipeTest"
    BotRobuste(equipe=nom_bot).connecter()