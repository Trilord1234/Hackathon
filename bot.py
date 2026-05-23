import socket
import time
import sys

# --- CONSTANTES ---
HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15

def get_secteur(l, c):
    """Retourne le secteur (0 à 3) d'une case."""
    if l <= 7:
        return 0 if c <= 8 else 1
    else:
        return 2 if c <= 8 else 3

def distance_rapide(l1, c1, l2, c2):
    """Distance de Tchebychev (très bonne approximation pour hexagones/hackathon)"""
    return max(abs(l1 - l2), abs(c1 - c2))

class SpiceBotUltime:
    def __init__(self, equipe="LesVersPythons"):
        self.equipe = equipe
        self.host = "127.0.0.1"
        self.port = 1234
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        self.mon_id = -1
        self.actions_restantes = MAX_ACTIONS
        self.plateau = {} # (l, c) -> {'densite': int, 'element': str, 'secteur': int}
        
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': get_secteur(l, c)}

    def envoyer_commande(self, cmd):
        """Envoie un message brut au serveur et retourne la réponse."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))
        return self.sock.recv(4096).decode('utf-8').strip()

    def envoyer_action(self, cmd):
        """Envoie une action de jeu si on n'a pas dépassé la limite des 15."""
        if self.actions_restantes > 0:
            rep = self.envoyer_commande(cmd)
            self.actions_restantes -= 1
            return rep
        return "NOK|Limite d'actions atteinte"

    def connecter(self):
        print(f"[*] Connexion au serveur {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        
        msg = self.sock.recv(1024).decode('utf-8').strip()
        if msg == "NOM_EQUIPE":
            reponse = self.envoyer_commande(self.equipe)
            print(f"[*] Réponse serveur: {reponse}")
            # Extraction de l'ID du joueur depuis "Bonjour Equipe vous êtes l'équipe | X"
            if "|" in reponse:
                self.mon_id = int(reponse.split('|')[1])
                print(f"[+] Mon ID de joueur est : {self.mon_id}")
        
        self.boucle_jeu()

    def actualiser_plateau(self):
        rep_densite = self.envoyer_commande("DENSITE")
        rep_elements = self.envoyer_commande("ELEMENTS")
        
        if len(rep_densite) >= HAUTEUR * LARGEUR and len(rep_elements) >= HAUTEUR * LARGEUR:
            for i in range(HAUTEUR * LARGEUR):
                l, c = divmod(i, LARGEUR)
                self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                self.plateau[(l, c)]['element'] = rep_elements[i]

    def obtenir_cases_par_element(self, element_type):
        return [(l, c) for (l, c), data in self.plateau.items() if data['element'] == str(element_type)]

    def boucle_jeu(self):
        print("[*] En attente du début de la partie (Appuyez sur ENTER dans le jeu)...")
        while True:
            msg = self.sock.recv(1024).decode('utf-8').strip()
            if not msg:
                continue
            
            if msg.startswith("DEBUT_TOUR"):
                tour = msg.split('|')[1]
                print(f"\n{'='*10} TOUR {tour} {'='*10}")
                self.actions_restantes = MAX_ACTIONS
                
                self.actualiser_plateau()
                rep_warning = self.envoyer_commande("WARNING")
                alertes_vers = rep_warning.split('|')
                print(f"[*] Alertes Vers: {alertes_vers}")
                
                self.jouer_tour(alertes_vers)
                
                print(f"[*] Fin du tour. Actions restantes non utilisées : {self.actions_restantes}")
                self.envoyer_commande("FINDETOUR")

    # ==========================================
    # LE CERVEAU DE L'IA (Stratégie Imitateur)
    # ==========================================
    def jouer_tour(self, alertes_vers):
        mes_recolteuses = self.obtenir_cases_par_element(self.mon_id)
        
        ennemis = []
        for i in range(4):
            if i != self.mon_id:
                ennemis.extend(self.obtenir_cases_par_element(i))

        # --- PRIORITÉ 1 : SURVIE (Esquiver les vers) ---
        for l, c in mes_recolteuses:
            secteur = get_secteur(l, c)
            if alertes_vers[secteur] == "DANGER":
                print(f"  [!] DANGER S{secteur} ! Évacuation de la récolteuse en ({l},{c})")
                # On cherche une case libre dans un secteur CALME ou INCONNU
                for (nl, nc), data in self.plateau.items():
                    if data['element'] == 'X' and alertes_vers[data['secteur']] != "DANGER":
                        self.envoyer_action(f"DEPLACER|{l}|{c}|{nl}|{nc}")
                        break

        # --- PRIORITÉ 2 : INTELLIGENCE (Déployer des ornithoptères) ---
        # Si on a des unités dans un secteur INCONNU, on pose un radar
        secteurs_occupes = {get_secteur(l, c) for l, c in mes_recolteuses}
        for s in secteurs_occupes:
            if alertes_vers[s] == "INCONNU":
                print(f"  [Radar] Déploiement d'un ornithoptère secteur {s}")
                self.envoyer_action(f"AJOUTERORNI|{s}")

        # --- PRIORITÉ 3 : RIPOSTE (Tit-for-Tat) ---
        # Si un ennemi est trop proche de nous (distance <= 2), on l'attaque en lui volant sa place
        for l, c in mes_recolteuses:
            for el, ec in ennemis:
                if distance_rapide(l, c, el, ec) <= 2:
                    print(f"  [Riposte] Ennemi détecté en ({el},{ec}). Blocage en cours !")
                    # Cherche une case de haute densité juste à côté de l'ennemi
                    meilleure_riposte = None
                    max_d = -1
                    for dl, dc in [(-1,0), (1,0), (0,-1), (0,1), (-1,-1), (1,1)]:
                        rl, rc = el + dl, ec + dc
                        if (rl, rc) in self.plateau and self.plateau[(rl, rc)]['element'] == 'X':
                            if self.plateau[(rl, rc)]['densite'] > max_d:
                                max_d = self.plateau[(rl, rc)]['densite']
                                meilleure_riposte = (rl, rc)
                    
                    if meilleure_riposte:
                        self.envoyer_action(f"DEPLACER|{l}|{c}|{meilleure_riposte[0]}|{meilleure_riposte[1]}")

        # --- PRIORITÉ 4 : EXPANSION (Farming Naïf) ---
        # Tant qu'on a des actions, on place de nouvelles récolteuses sur l'épice dense (Loin des vers et ennemis)
        cases_libres = [(l, c) for (l, c), data in self.plateau.items() if data['element'] == 'X']
        # On trie par densité décroissante
        cases_libres.sort(key=lambda coord: self.plateau[coord]['densite'], reverse=True)

        for l, c in cases_libres:
            if self.actions_restantes <= 0:
                break
                
            secteur = get_secteur(l, c)
            if alertes_vers[secteur] == "DANGER":
                continue # On ne spawn pas dans la gueule du ver
                
            # Vérifier qu'il n'y a pas d'ennemis juste à côté pour éviter les embrouilles
            ennemi_proche = False
            for el, ec in ennemis:
                if distance_rapide(l, c, el, ec) <= 2:
                    ennemi_proche = True
                    break
            
            if not ennemi_proche:
                print(f"  [Farming] Achat récolteuse sur case riche en ({l},{c})")
                self.envoyer_action(f"AJOUTERRECOLTEUSE|{l}|{c}")

if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "Les_Maitres_Du_Code"
    bot = SpiceBotUltime(equipe=nom_equipe)
    try:
        bot.connecter()
    except KeyboardInterrupt:
        print("\n[!] Arrêt du Bot.")
    except Exception as e:
        print(f"[X] Erreur critique : {e}")