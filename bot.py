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
    # 1. On liste nos récolteuses et leurs positions
    mes_recolteuses = [(l, c) for (l, c), data in self.plateau.items() 
                       if data['element'] == str(self.mon_id)]
    
    # 2. Vérifier si on se fait "Tricher" (un ennemi trop proche de nous)
    ennemis_proches = []
    for rl, rc in mes_recolteuses:
        # Fonction imaginaire qui regarde les cases adjacentes
        voisins = self.obtenir_voisins(rl, rc) 
        for vl, vc in voisins:
            element = self.plateau[(vl, vc)]['element']
            if element in ['0', '1', '2', '3'] and element != str(self.mon_id):
                ennemis_proches.append(element)
    
    # 3. PRISE DE DÉCISION (La théorie de l'Imitateur)
    if ennemis_proches:
        # MODE PUNITION (Triche)
        # On consacre nos actions à bloquer/fuir l'ennemi qui nous colle
        id_ennemi = ennemis_proches[0]
        print(f"L'ennemi {id_ennemi} s'approche ! Mode Défense/Punition activé.")
        # TODO: Coder la logique pour envoyer une commande DEPLACER vers l'ennemi
        # self.envoyer_commande(f"DEPLACER|{...}")
        
    else:
        # MODE COOPÉRATION (Vivre et laisser vivre)
        # Personne ne nous embête, on maximise notre profit sereinement
        meilleure_case = self.trouver_meilleure_case_epice_isolee()
        if meilleure_case:
            print(f"Zone calme. Récolte optimale sur {meilleure_case}.")
            # TODO: Coder la logique pour AJOUTERRECOLTEUSE ou avancer vers la case

if __name__ == "__main__":
    bot = SpiceBot(equipe="HackathonDiag")
    try:
        bot.connecter()
    except KeyboardInterrupt:
        print("\nBot arrêté.")
    except Exception as e:
        print(f"Erreur: {e}")