import socket
import time

# --- CONSTANTES DU PLATEAU ---
HAUTEUR = 16
LARGEUR = 18

def get_secteur(l, c):
    """Retourne le numéro du secteur (0 à 3) selon les coordonnées."""
    if l <= 7:
        return 0 if c <= 8 else 1
    else:
        return 2 if c <= 8 else 3

class SpiceBot:
    def __init__(self, equipe="ESE'OCTET"):
        self.equipe = equipe
        self.host = "127.0.0.1"
        self.port = 1234
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Le plateau sera un dictionnaire: (ligne, colonne) -> { 'densite': int, 'element': str, 'secteur': int }
        self.plateau = {}
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': get_secteur(l, c)}

    def envoyer_commande(self, cmd):
        """Envoie une commande et retourne la réponse du serveur."""
        # On suppose que le serveur attend un message et qu'on reçoit une réponse directe
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        # Attente de la réponse (on prend un buffer large)
        reponse = self.sock.recv(4096).decode('utf-8').strip()
        return reponse

    def connecter(self):
        print(f"Connexion au serveur {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        
        # Le serveur demande NOM_EQUIPE
        msg = self.sock.recv(1024).decode('utf-8').strip()
        if msg == "NOM_EQUIPE":
            reponse = self.envoyer_commande(self.equipe)
            print(f"Serveur: {reponse}")
        
        self.boucle_jeu()

    def actualiser_plateau(self):
        """Met à jour le dictionnaire du plateau avec les données du serveur."""
        # 1. Densité
        rep_densite = self.envoyer_commande("DENSITE")
        if len(rep_densite) == HAUTEUR * LARGEUR:
            for i, char in enumerate(rep_densite):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l, c)]['densite'] = int(char)

        # 2. Éléments (Récolteuses, Usines, Vide)
        rep_elements = self.envoyer_commande("ELEMENTS")
        if len(rep_elements) == HAUTEUR * LARGEUR:
            for i, char in enumerate(rep_elements):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l, c)]['element'] = char

    def boucle_jeu(self):
        print("En attente du début de la partie...")
        while True:
            # On écoute les messages entrants (DEBUT_TOUR)
            msg = self.sock.recv(1024).decode('utf-8').strip()
            if not msg:
                continue
            
            if msg.startswith("DEBUT_TOUR"):
                tour = msg.split('|')[1]
                print(f"\n--- TOUR {tour} ---")
                
                # Mise à jour de notre vision du jeu
                self.actualiser_plateau()
                
                # Vérification des vers des sables
                rep_warning = self.envoyer_commande("WARNING")
                etats_secteurs = rep_warning.split('|')
                print(f"Alertes Vers: {etats_secteurs}")
                
                # ==========================================
                # C'EST ICI QUE VOTRE INTELLIGENCE INTERVIENT
                # ==========================================
                self.reflechir_et_agir(etats_secteurs)
                
                # Fin du tour obligatoire
                self.envoyer_commande("FINDETOUR")

    def reflechir_et_agir(self, alertes_vers):
        """
        Logique de l'IA. Limite: 15 commandes max par tour. 5 secondes max.
        Commandes utiles : 
        - self.envoyer_commande("AJOUTERRECOLTEUSE|l|c")
        - self.envoyer_commande("DEPLACER|l1|c1|l2|c2")
        - self.envoyer_commande("AJOUTERORNI|secteur")
        """
        # Exemple de logique ultra basique : Placer un orni si on ne sait rien du secteur 0
        if alertes_vers[0] == "INCONNU":
            print("Action: Déploiement Orni Secteur 0")
            self.envoyer_commande("AJOUTERORNI|0")
            
        # TODO : Parcourir self.plateau pour trouver la meilleure case 'X' avec la plus haute 'densite'
        # TODO : Vérifier qu'on a l'argent (5000) et faire AJOUTERRECOLTEUSE

if __name__ == "__main__":
    bot = SpiceBot(equipe="HackathonDiag")
    try:
        bot.connecter()
    except KeyboardInterrupt:
        print("\nBot arrêté.")
    except Exception as e:
        print(f"Erreur: {e}")