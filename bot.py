import socket
import select
import sys
import Maps

HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15
PRIX_RECOLTEUSE = 5000

def get_secteur(l, c):
    if l <= 7: return 0 if c <= 8 else 1
    else: return 2 if c <= 8 else 3

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class SpiceBotChampion:
    def __init__(self, equipe="Muad_Dib"):
        self.equipe = equipe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.actions_restantes = MAX_ACTIONS
        self.plateau = {}
        
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': get_secteur(l, c)}

    # ── RÉSEAU ROBUSTE ───────────────────────────────────────────────────────
    def connecter(self):
        print(f"[*] Connexion de l'IA {self.equipe}...")
        self.sock.connect(("127.0.0.1", 1234))
        while True:
            for msg in self.lire_reseau(0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    self.mon_id = int(msg.split('|')[1])
                    print(f"[+] ID obtenu : {self.mon_id}")
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
        self.envoyer(cmd)
        while True:
            for msg in self.lire_reseau(0.02):
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288: return msg
                elif cmd in ["WARNING", "SCORES"] and "|" in msg and "DEBUT_TOUR" not in msg: return msg

    def envoyer_action(self, cmd):
        if self.actions_restantes > 0:
            self.envoyer(cmd)
            self.actions_restantes -= 1
            return True
        return False

    # ── MOTEUR DE CHALEUR (HEAT MAP) ─────────────────────────────────────────
    def generer_heatmap(self, alertes_vers, ennemis, usines_ennemies):
        """
        Calcule le score de désirabilité de CHAQUE case libre du plateau.
        Mixe rentabilité pure et sabotage (Parasitisme + Baiting).
        """
        scores_cases = []
        
        # Compter les ennemis par secteur pour le "Baiting" (Attirer le ver)
        population_secteur = {0:0, 1:0, 2:0, 3:0}
        for el, ec in ennemis:
            population_secteur[get_secteur(el, ec)] += 1

        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                data = self.plateau[(l, c)]
                if data['element'] != 'X':
                    continue # On ne note que les cases libres
                
                sect = data['secteur']
                if alertes_vers[sect] == "DANGER":
                    continue # Score éliminatoire, on l'ignore

                # 1. Valeur de base (Densité)
                score = data['densite'] * 10
                if score == 0:
                    continue # Inutile de viser le vide

                # 2. Parasitisme Industriel
                est_proche_usine_ennemie = any(distance(l, c, ul, uc) <= 2 for ul, uc in usines_ennemies)
                if est_proche_usine_ennemie:
                    score *= 2 # Rentabilité doublée gratuitement !

                # 3. Worm Baiting (Sabotage Indirect)
                # On soustrait des points en fonction de la population ennemie du secteur
                # Si un secteur est bourré d'ennemis, on le fuit pour que le ver y aille.
                score -= (population_secteur[sect] * 5)

                scores_cases.append({'l': l, 'c': c, 'score': score})
        
        # Tri du plus chaud au plus froid
        scores_cases.sort(key=lambda x: x['score'], reverse=True)
        return scores_cases

    # ── BOUCLE STRATÉGIQUE ───────────────────────────────────────────────────
    def boucle_jeu(self):
        while True:
            for msg in self.lire_reseau(0.1):
                if msg.startswith("DEBUT_TOUR"):
                    tour = msg.split('|')[1]
                    print(f"\n🔥 TOUR {tour} 🔥")
                    self.actions_restantes = MAX_ACTIONS
                    
                    rep_densite = self.requete("DENSITE")
                    rep_elements = self.requete("ELEMENTS")
                    alertes_vers = self.requete("WARNING").split('|')
                    scores = self.requete("SCORES").split('|')
                    
                    try: mon_budget = int(scores[self.mon_id])
                    except: mon_budget = 0
                    
                    for i in range(HAUTEUR * LARGEUR):
                        l, c = divmod(i, LARGEUR)
                        self.plateau[(l, c)]['densite'] = int(rep_densite[i])
                        self.plateau[(l, c)]['element'] = rep_elements[i]
                        Maps.maps['obj'][l][c] = rep_elements[i]
                        Maps.maps['dns'][l][c] = rep_densite[i]

                    self.jouer_tour(alertes_vers, mon_budget)
                    self.envoyer("FINDETOUR")

    def jouer_tour(self, alertes_vers, mon_budget):
        mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
        ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
        usines_ennemies = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'U'] # Simplification (Toutes les usines)

        # 1. URGENCE : Fuite précise avec Maps.py
        ordres_evac = Maps.evacuation_protocol(Maps.maps, self.mon_id, alertes_vers)
        for ordre in ordres_evac:
            if self.envoyer_action(f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}|{ordre['dest_y']}|{ordre['dest_x']}"):
                print(f"  [SURVIE] Fuite ({ordre['orig_y']},{ordre['orig_x']}) -> ({ordre['dest_y']},{ordre['dest_x']})")

        # 2. RENSEIGNEMENT
        secteurs_occupes = {self.plateau[(l, c)]['secteur'] for l, c in mes_unites}
        for sect in secteurs_occupes:
            if alertes_vers[sect] == "INCONNU":
                self.envoyer_action(f"AJOUTERORNI|{sect}")

        # 3. GÉNÉRATION DE LA HEAT MAP
        heatmap = self.generer_heatmap(alertes_vers, ennemis, usines_ennemies)
        
        # 4. ESSAIM MOBILE (Assèchement)
        for l, c in mes_unites:
            if self.actions_restantes <= 0: break
            densite_actuelle = self.plateau[(l, c)]['densite']
            case_partagee = any(distance(l, c, el, ec) == 0 for el, ec in ennemis)
            
            if densite_actuelle <= 1 or case_partagee:
                # On prend la meilleure case de la Heat Map
                if heatmap:
                    cible = heatmap.pop(0) # On la retire pour ne pas envoyer 2 unités au même endroit
                    self.envoyer_action(f"DEPLACER|{l}|{c}|{cible['l']}|{cible['c']}")
                    print(f"  [MIGRATION] -> Spot de chaleur {cible['score']} en ({cible['l']},{cible['c']})")

        # 5. EXPANSION (Achats basés sur la chaleur)
        while mon_budget >= PRIX_RECOLTEUSE and self.actions_restantes > 0 and heatmap:
            cible = heatmap.pop(0)
            # Règle anti-conflit primaire : on ne spawn pas à côté d'un ennemi sans usine
            if not any(distance(cible['l'], cible['c'], el, ec) <= 2 for el, ec in ennemis):
                if self.envoyer_action(f"AJOUTERRECOLTEUSE|{cible['l']}|{cible['c']}"):
                    print(f"  [ACHAT] Nouvelle récolteuse sur case chaude ({cible['l']},{cible['c']})")
                    mon_budget -= PRIX_RECOLTEUSE


if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "LesMaitresDuCode"
    bot = SpiceBotChampion(equipe=nom_equipe)
    try: bot.connecter()
    except KeyboardInterrupt: print("\n[!] Fin.")