import socket
import select
import sys
import Maps

# --- CONFIGURATION ET CONSTANTES ---
HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15
PRIX_RECOLTEUSE = 5000
PRIX_USINE = 10000

def get_secteur_de_case(l, c):
    """Calcule le secteur (0 à 3) d'une case selon les règles du plateau."""
    if l <= 7:
        return 0 if c <= 8 else 1
    else:
        return 2 if c <= 8 else 3

class SpiceBotPrincipal:
    def __init__(self, equipe="Family_Atreides"):
        self.equipe = equipe
        self.host = "127.0.0.1"
        self.port = 1234
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        self.mon_id = -1
        self._buffer = ""
        self.actions_restantes = MAX_ACTIONS
        self.plateau = {}
        
        # Initialisation du référentiel local
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 1, 'element': 'X', 'secteur': get_secteur_de_case(l, c)}

    # ── PLOMBERIE RÉSEAU ROBUSTE ─────────────────────────────────────────────
    
    def connecter(self):
        print(f"[*] Connexion au serveur de jeu sur {self.host}:{self.port}...")
        self.sock.connect((self.host, self.port))
        
        while True:
            for msg in self.lire_reseau(timeout=0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    self.mon_id = int(msg.split('|')[1])
                    print(f"[+] Authentifié avec succès. Mon ID Joueur : {self.mon_id}")
                    self.boucle_jeu()
                    return

    def envoyer(self, cmd):
        """Envoie une commande brute avec saut de ligne réglementaire."""
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def envoyer_action(self, cmd):
        """Envoie une action de jeu et décrémente le compteur de bande passante du tour."""
        if self.actions_restantes > 0:
            self.envoyer(cmd)
            self.actions_restantes -= 1
            return True
        return False

    def lire_reseau(self, timeout=0.05):
        """Consomme le flux TCP sans jamais bloquer l'exécution ni vider le buffer."""
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if ready:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                print("[!] Connexion interrompue par le serveur.")
                sys.exit()
            self._buffer += data

        lignes = []
        while '\n' in self._buffer:
            ligne, self._buffer = self._buffer.split('\n', 1)
            lignes.append(ligne.strip())
        return [l for l in lignes if l]

    def requete(self, cmd):
        """Effectue une demande d'état et isole sa réponse synchrone."""
        self.envoyer(cmd)
        while True:
            for msg in self.lire_reseau(timeout=0.02):
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288:
                    return msg
                elif cmd in ["WARNING", "SCORES"] and "|" in msg and "DEBUT_TOUR" not in msg:
                    return msg
                elif msg.startswith("NOK"):
                    print(f"[-] Erreur action enregistrée : {msg}")

    # ── BOUCLE DE JEU ET SYNCHRONISATION ─────────────────────────────────────
    
    def boucle_jeu(self):
        print("[*] En attente du coup d'envoi du serveur...")
        while True:
            for msg in self.lire_reseau(timeout=0.1):
                if msg.startswith("DEBUT_TOUR"):
                    tour = msg.split('|')[1]
                    print(f"\n⚡ {'='*12} DEBUT DU TOUR {tour} {'='*12}")
                    self.actions_restantes = MAX_ACTIONS
                    self.synchroniser_et_penser()

    def synchroniser_et_penser(self):
        # 1. Collecte des données du serveur
        rep_densite = self.requete("DENSITE")
        rep_elements = self.requete("ELEMENTS")
        alertes_vers = self.requete("WARNING").split('|')
        scores_bruts = self.requete("SCORES").split('|')

        try:
            mon_budget = int(scores_bruts[self.mon_id])
            print(f"[*] Trésorerie : {mon_budget} Épice | Actions max du tour : {self.actions_restantes}")
        except Exception:
            mon_budget = 0

        # 2. Synchronisation bidirectionnelle avec Maps.py
        for i in range(HAUTEUR * LARGEUR):
            l, c = divmod(i, LARGEUR)
            self.plateau[(l, c)]['densite'] = int(rep_densite[i])
            self.plateau[(l, c)]['element'] = rep_elements[i]
            
            # Injection directe dans les structures de Maps.py (y=ligne, x=colonne)
            Maps.maps['obj'][l][c] = rep_elements[i]
            Maps.maps['dns'][l][c] = rep_densite[i]

        # 3. Exécution de l'arbre de décision stratégique
        self.ordonnancer_actions(alertes_vers, mon_budget)
        
        # 4. Clôture impérative du tour
        self.envoyer("FINDETOUR")
        print("[*] Ordre FINDETOUR transmis.")

    # ── LOGIQUE STRATÉGIQUE AVANCÉE ──────────────────────────────────────────
    
    def ordonnancer_actions(self, alertes_vers, mon_budget):
        # Identification des positions des entités
        mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
        unites_ennemies = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
        usines_presentes = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'U']

        # --- STRATÉGIE 1 : URGENCE & ÉVACUATION HEXAGONALE (Maps.py) ---
        # Appel direct de votre protocole d'évacuation basé sur le voisinage à décalage de lignes
        ordres_evac = Maps.evacuation_protocol(Maps.maps, self.mon_id, alertes_vers)
        if ordres_evac:
            print(f"[!] Rappel d'urgence : {len(ordres_evac)} unités menacées par les vers.")
            for ordre in ordres_evac:
                # Maps utilise x (colonne) et y (ligne)
                l1, c1 = ordre['orig_y'], ordre['orig_x']
                l2, c2 = ordre['dest_y'], ordre['dest_x']
                if self.envoyer_action(f"DEPLACER|{l1}|{c1}|{l2}|{c2}"):
                    print(f"    -> [Évacuation] ({l1},{c1}) de déplacée vers la zone sûre ({l2},{c2})")

        # --- STRATÉGIE 2 : COUVERTURE RADAR DE SÉCURITÉ ---
        secteurs_exploites = {self.plateau[(l, c)]['secteur'] for l, c in mes_unites}
        for sect in secteurs_exploites:
            if alertes_vers[sect] == "INCONNU":
                if self.envoyer_action(f"AJOUTERORNI|{sect}"):
                    print(f"    -> [Radar] Déploiement d'un ornithoptère sur le Secteur {sect}")

        # --- STRATÉGIE 3 : ANTI-COLOCATION & RE-LOCALISATION MOBILE ---
        for l, c in mes_unites:
            # Si la case s'épuise ou si un intrus partage la case (vitesse divisée), on bouge
            case_partagee = any(el == 'X' for el in [self.plateau[(l,c)]['element']] if el != str(self.mon_id) and el != 'X')
            if (self.plateau[(l, c)]['densite'] <= 1 or case_partagee) and self.actions_restantes > 0:
                # Extraction des meilleures cibles globales fournies par Maps
                res_spots = Maps.find_best_locations(Maps.maps, top_n=30)
                spots = res_spots["top_spots"] if isinstance(res_spots, dict) else res_spots
                
                for spot in spots:
                    sl, sc = (spot['l'], spot['c']) if 'l' in spot else (spot['y'], spot['x'])
                    if self.plateau[(sl, sc)]['element'] == 'X' and alertes_vers[get_secteur_de_case(sl, sc)] != "DANGER":
                        if self.envoyer_action(f"DEPLACER|{l}|{c}|{sl}|{sc}"):
                            print(f"    -> [Migration] Unité déplacée de la case pauvre ou surchargée ({l},{c}) vers ({sl},{sc})")
                            break

        # --- STRATÉGIE 4 : EXPANSION ET PARASITISME INDUSTRIEL ---
        # Récupération des spots à haut rendement calculés géométriquement par Maps
        donnees_spots = Maps.find_best_locations(Maps.maps, top_n=20)
        spots_expansion = donnees_spots["top_spots"] if isinstance(donnees_spots, dict) else donnees_spots

        # Tri et filtrage pour appliquer la diversification (éviter d'empiler tout le monde au même endroit)
        for spot in spots_expansion:
            if self.actions_restantes <= 0:
                break
            
            sl = spot['l'] if 'l' in spot else spot['y']
            sc = spot['c'] if 'c' in spot else spot['x']
            secteur_cible = get_secteur_de_case(sl, sc)

            # Sécurité anti-ver : Ne jamais investir dans un secteur condamné à court terme
            if alertes_vers[secteur_cible] == "DANGER":
                continue

            # Vérification de la présence d'une usine à proximité immédiate pour profiter du bonus x2 gratuit
            proche_usine_existante = any(max(abs(sl - ul), abs(sc - uc)) <= 2 for ul, uc in usines_presentes)

            # Décision d'investissement : Usine propre vs Récolteuse
            if mon_budget >= PRIX_USINE and len(mes_unites) >= 4 and not proche_usine_existante:
                if self.envoyer_action(f"AJOUTERUSINE|{sl}|{sc}"):
                    print(f"    -> [Industrie] Construction d'une usine centrale en ({sl},{sc})")
                    mon_budget -= PRIX_USINE
                    usines_presentes.append((sl, sc))
            elif mon_budget >= PRIX_RECOLTEUSE:
                # Diversification tactique : Ne pas surcharger un secteur déjà saturé pour ne pas attirer les vers
                nb_unites_secteur = sum(1 for u in mes_unites if get_secteur_de_case(u[0], u[1]) == secteur_cible)
                if nb_unites_secteur > 5: 
                    continue # On cherche un autre spot dans un secteur moins peuplé

                if self.envoyer_action(f"AJOUTERRECOLTEUSE|{sl}|{sc}"):
                    print(f"    -> [Expansion] Déploiement d'une récolteuse sur spot optimal ({sl},{sc})")
                    mon_budget -= PRIX_RECOLTEUSE

if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "LesMaitresDuCode"
    bot = SpiceBotPrincipal(equipe=nom_equipe)
    try:
        bot.connecter()
    except KeyboardInterrupt:
        print("\n[!] Déconnexion demandée par l'opérateur.")