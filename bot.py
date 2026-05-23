import socket
import select
import sys
import Maps

HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15
PRIX_RECOLTEUSE = 5000
PRIX_USINE = 10000

def get_secteur(l, c):
    if l <= 7: return 0 if c <= 8 else 1
    else: return 2 if c <= 8 else 3

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class SpiceBotChampion:
    def __init__(self, equipe="Atreides"):
        self.equipe = equipe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.actions_restantes = MAX_ACTIONS
        self.plateau = {}
        
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': get_secteur(l, c)}

    # ── RÉSEAU BLINDÉ (ANTI-CRASH) ───────────────────────────────────────────
    def connecter(self):
        print(f"[*] Déploiement de la faction : {self.equipe}...")
        self.sock.connect(("127.0.0.1", 1234))
        while True:
            for msg in self.lire_reseau(0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    # Extraction robuste de l'ID
                    parties = msg.split('|')
                    if len(parties) > 1:
                        self.mon_id = int(parties[1].strip())
                        print(f"[+] Authentifié ! Mon ID : {self.mon_id}")
                        self.boucle_jeu()
                        return

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
        """Demande sécurisée avec un timeout max de 1 seconde (50 * 0.02s)"""
        self.envoyer(cmd)
        tentatives = 0
        while tentatives < 50:
            for msg in self.lire_reseau(0.02):
                if "DEBUT_TOUR" in msg or msg == "OK" or msg.startswith("NOK"):
                    continue # On ignore la pollution asynchrone
                
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288: 
                    return msg
                elif cmd == "WARNING" and "|" in msg: 
                    return msg
                elif cmd == "SCORES" and any(c.isdigit() for c in msg): 
                    return msg
            tentatives += 1
            
        # --- FAILSAFE (Si le serveur bug, on évite le freeze du tour) ---
        if cmd == "WARNING": return "INCONNU|INCONNU|INCONNU|INCONNU"
        if cmd == "SCORES": return "0"
        return "X" * 288 # Fausse carte vide pour survivre

    def envoyer_action(self, cmd):
        if self.actions_restantes > 0:
            self.envoyer(cmd)
            self.actions_restantes -= 1
            return True
        return False

    # ── INTELLIGENCE & HEAT MAP ──────────────────────────────────────────────
    def generer_heatmap(self, alertes_vers, ennemis, usines_ennemies):
        scores_cases = []
        population_secteur = {0:0, 1:0, 2:0, 3:0}
        
        for el, ec in ennemis:
            population_secteur[get_secteur(el, ec)] += 1

        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                data = self.plateau[(l, c)]
                if data['element'] != 'X': continue
                
                sect = data['secteur']
                if alertes_vers[sect] == "DANGER": continue

                score = data['densite'] * 10
                if score == 0: continue

                # Bonus si proche d'une usine ennemie (Parasitisme)
                if any(distance(l, c, ul, uc) <= 2 for ul, uc in usines_ennemies):
                    score *= 2

                # Malus si le secteur est bondé d'ennemis (Appât à vers)
                score -= (population_secteur[sect] * 5)

                scores_cases.append({'l': l, 'c': c, 'score': score})
        
        scores_cases.sort(key=lambda x: x['score'], reverse=True)
        return scores_cases

    # ── BOUCLE STRATÉGIQUE PRINCIPALE ────────────────────────────────────────
    def boucle_jeu(self):
        tour_actuel = 0
        while True:
            for msg in self.lire_reseau(0.1):
                if msg.startswith("DEBUT_TOUR"):
                    try:
                        tour_actuel = int(msg.split('|')[1])
                        print(f"\n🔥 TOUR {tour_actuel} 🔥")
                    except: pass
                    
                    self.actions_restantes = MAX_ACTIONS
                    
                    # 1. Collecte des données
                    rep_densite = self.requete("DENSITE")
                    rep_elements = self.requete("ELEMENTS")
                    alertes_vers = self.requete("WARNING").split('|')
                    scores_bruts = self.requete("SCORES").split('|')
                    
                    # Parsing robuste du budget
                    try:
                        if 0 <= self.mon_id < len(scores_bruts):
                            mon_budget = int(scores_bruts[self.mon_id])
                        else:
                            mon_budget = int(scores_bruts[0])
                    except: mon_budget = 0
                    
                    # 2. Mise à jour de notre cerveau et de Maps.py
                    for i in range(HAUTEUR * LARGEUR):
                        l, c = divmod(i, LARGEUR)
                        self.plateau[(l, c)]['densite'] = int(rep_densite[i]) if rep_densite[i].isdigit() else 0
                        self.plateau[(l, c)]['element'] = rep_elements[i]
                        
                        try:
                            Maps.maps['obj'][l][c] = rep_elements[i]
                            Maps.maps['dns'][l][c] = rep_densite[i]
                        except: pass # Failsafe si Maps.py a une structure différente

                    # 3. Réflexion et Action
                    self.jouer_tour(alertes_vers, mon_budget, tour_actuel)
                    
                    # 4. Fin de tour obligatoire
                    self.envoyer("FINDETOUR")

    def jouer_tour(self, alertes_vers, mon_budget, tour_actuel):
        mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
        ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
        usines_ennemies = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'U']

        # --- PHASE 1 : URGENCE (Fuite avec Maps.py) ---
        try:
            ordres_evac = Maps.evacuation_protocol(Maps.maps, self.mon_id, alertes_vers)
            for ordre in ordres_evac:
                if self.envoyer_action(f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}|{ordre['dest_y']}|{ordre['dest_x']}"):
                    print(f"  [SURVIE] Évacuation ({ordre['orig_y']},{ordre['orig_x']}) -> ({ordre['dest_y']},{ordre['dest_x']})")
        except Exception as e:
            print(f"  [!] Erreur Maps.py ignorée : {e}")

        # --- PHASE 2 : RENSEIGNEMENT ---
        secteurs_occupes = {self.plateau[(l, c)]['secteur'] for l, c in mes_unites}
        for sect in secteurs_occupes:
            if len(alertes_vers) > sect and alertes_vers[sect] == "INCONNU":
                self.envoyer_action(f"AJOUTERORNI|{sect}")

        # --- PHASE 3 : GÉNÉRATION HEAT MAP ---
        heatmap = self.generer_heatmap(alertes_vers, ennemis, usines_ennemies)

        # --- PHASE 4 : MIGRATION (Quitter les cases pauvres) ---
        for l, c in mes_unites:
            if self.actions_restantes <= 0: break
            densite = self.plateau[(l, c)]['densite']
            partage = any(distance(l, c, el, ec) == 0 for el, ec in ennemis)
            
            if densite <= 1 or partage:
                if heatmap:
                    cible = heatmap.pop(0)
                    self.envoyer_action(f"DEPLACER|{l}|{c}|{cible['l']}|{cible['c']}")
                    print(f"  [MIGRATION] Transfert vers spot de chaleur {cible['score']} en ({cible['l']},{cible['c']})")

        # --- PHASE 5 : EXPANSION (Geler les achats en fin de partie) ---
        if tour_actuel < 185: # On n'achète plus rien dans les 15 derniers tours !
            while mon_budget >= PRIX_RECOLTEUSE and self.actions_restantes > 0 and heatmap:
                cible = heatmap.pop(0)
                # On évite de s'étendre collé à un ennemi (sauf si c'est pour parasiter son usine)
                if not any(distance(cible['l'], cible['c'], el, ec) <= 1 for el, ec in ennemis):
                    if self.envoyer_action(f"AJOUTERRECOLTEUSE|{cible['l']}|{cible['c']}"):
                        print(f"  [ACHAT] Récolteuse déployée en ({cible['l']},{cible['c']})")
                        mon_budget -= PRIX_RECOLTEUSE

if __name__ == "__main__":
    # Récupère le nom passé dans la console, sinon utilise "ESEO_Bot"
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "ESEO_Bot"
    bot = SpiceBotChampion(equipe=nom_equipe)
    try: bot.connecter()
    except KeyboardInterrupt: print("\n[!] Déconnexion.")