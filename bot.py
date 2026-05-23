import socket
import select
import sys
import random
import Maps

# --- NOUVEAUX PRIX OFFICIELS ---
HAUTEUR = 16
LARGEUR = 18
MAX_ACTIONS = 15
PRIX_RECOLTEUSE = 3000
PRIX_USINE = 5000
PRIX_ORNI = 400
PRIX_SABOTAGE = 500

def get_secteur(l, c):
    if l <= 7: return 0 if c <= 8 else 1
    else: return 2 if c <= 8 else 3

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class SpiceBotEsport:
    def __init__(self, equipe="Atreides_Prime"):
        self.equipe = equipe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.actions_restantes = MAX_ACTIONS
        self.plateau = {}
        
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': get_secteur(l, c)}

    # ── 1. RÉSEAU BLINDÉ ─────────────────────────────────────────────────────
    
    def connecter(self):
        print(f"[*] Démarrage de l'IA Assassin : {self.equipe}...")
        self.sock.connect(("127.0.0.1", 1234))
        while True:
            for msg in self.lire_reseau(0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    parties = msg.split('|')
                    if len(parties) > 1:
                        self.mon_id = int(parties[1].strip())
                        print(f"[+] Prêt à dominer ! Mon ID : {self.mon_id}")
                        self.boucle_jeu()
                        return

    def envoyer(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def envoyer_action(self, cmd):
        if self.actions_restantes > 0:
            self.envoyer(cmd)
            self.actions_restantes -= 1
            return True
        return False

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
        tentatives = 0
        while tentatives < 50:
            for msg in self.lire_reseau(0.02):
                if "DEBUT_TOUR" in msg or msg == "OK" or msg.startswith("NOK"):
                    continue 
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288: return msg
                elif cmd == "WARNING" and "|" in msg: return msg
                elif cmd == "SCORES" and any(c.isdigit() for c in msg): return msg
            tentatives += 1
            
        if cmd == "WARNING": return "INCONNU|INCONNU|INCONNU|INCONNU"
        if cmd == "SCORES": return "0|0|0|0"
        return "X" * 288 

    # ── 2. HEAT MAP ──────────────────────────────────────────────────────────
    
    def generer_heatmap(self, alertes_vers, ennemis, usines_ennemies, secteurs_condamnes):
        scores_cases = []
        
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                data = self.plateau[(l, c)]
                if data['element'] != 'X': continue
                
                sect = data['secteur']
                # Si le secteur est en danger NATUREL, ou si on vient de le SABOTER nous-mêmes
                if alertes_vers[sect] == "DANGER" or sect in secteurs_condamnes: 
                    continue

                score = data['densite'] * 10
                if score <= 0: continue

                # Bonus si on est proche d'une usine (amie ou ennemie)
                if any(distance(l, c, ul, uc) <= 2 for ul, uc in usines_ennemies):
                    score *= 2

                scores_cases.append({'l': l, 'c': c, 'score': score, 'sect': sect})
        
        random.shuffle(scores_cases) 
        scores_cases.sort(key=lambda x: x['score'], reverse=True)
        return scores_cases

    # ── 3. BOUCLE DE JEU ─────────────────────────────────────────────────────
    
    def boucle_jeu(self):
        tour_actuel = 0
        while True:
            for msg in self.lire_reseau(0.1):
                if msg.startswith("DEBUT_TOUR"):
                    try:
                        tour_actuel = int(msg.split('|')[1])
                        print(f"\n{'='*15} TOUR {tour_actuel} {'='*15}")
                    except: pass
                    
                    self.actions_restantes = MAX_ACTIONS
                    
                    # Consomme 4 actions
                    rep_densite = self.requete("DENSITE")
                    self.actions_restantes -= 1
                    rep_elements = self.requete("ELEMENTS")
                    self.actions_restantes -= 1
                    alertes_vers = self.requete("WARNING").split('|')
                    self.actions_restantes -= 1
                    scores_bruts = self.requete("SCORES").split('|')
                    self.actions_restantes -= 1
                    
                    try:
                        if 0 <= self.mon_id < len(scores_bruts):
                            mon_budget = int(scores_bruts[self.mon_id])
                        else: mon_budget = int(scores_bruts[0])
                        print(f"[*] Argent disponible : {mon_budget} | Actions restantes : {self.actions_restantes}")
                    except: mon_budget = 0
                    
                    for i in range(HAUTEUR * LARGEUR):
                        l, c = divmod(i, LARGEUR)
                        self.plateau[(l, c)]['densite'] = int(rep_densite[i]) if rep_densite[i].isdigit() else 0
                        self.plateau[(l, c)]['element'] = rep_elements[i]
                        try:
                            Maps.maps['obj'][l][c] = rep_elements[i]
                            Maps.maps['dns'][l][c] = rep_densite[i]
                        except: pass 

                    self.jouer_tour(alertes_vers, tour_actuel, mon_budget)
                    self.envoyer("FINDETOUR")

    def jouer_tour(self, alertes_vers, tour_actuel, mon_budget):
        mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
        ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
        usines_actives = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'U']

        secteurs_condamnes = set() # Pour stocker les secteurs qu'on va saboter ce tour-ci

        # --- PHASE 1 : URGENCE (Fuite avec Maps.py) ---
        try:
            ordres_evac = Maps.evacuation_protocol(Maps.maps, self.mon_id, alertes_vers)
            for ordre in ordres_evac:
                if self.envoyer_action(f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}|{ordre['dest_y']}|{ordre['dest_x']}"):
                    print(f"  [SURVIE] Fuite : ({ordre['orig_y']},{ordre['orig_x']}) -> ({ordre['dest_y']},{ordre['dest_x']})")
        except: pass

        # --- PHASE 2 : LE SABOTAGE TOXIQUE ---
        # On compte les forces en présence
        ennemis_par_sect = {0:0, 1:0, 2:0, 3:0}
        allies_par_sect = {0:0, 1:0, 2:0, 3:0}
        for el, ec in ennemis: ennemis_par_sect[get_secteur(el, ec)] += 1
        for ml, mc in mes_unites: allies_par_sect[get_secteur(ml, mc)] += 1

        for sect in range(4):
            # Si le secteur pullule d'ennemis (>= 2) et qu'on n'y a personne (pour éviter le tir allié)
            if ennemis_par_sect[sect] >= 2 and allies_par_sect[sect] == 0:
                if mon_budget >= PRIX_SABOTAGE and alertes_vers[sect] != "DANGER":
                    if self.envoyer_action(f"SABOTER|{sect}"):
                        print(f"  [ASSASSINAT] 💥 Frappe orbitale demandée sur le Secteur {sect} ! (Victimes estimées : {ennemis_par_sect[sect]})")
                        mon_budget -= PRIX_SABOTAGE
                        secteurs_condamnes.add(sect) # On s'interdit d'y aller pendant ce tour !

        # --- PHASE 3 : RENSEIGNEMENT (Radars) ---
        secteurs_occupes = {get_secteur(l, c) for l, c in mes_unites}
        for sect in secteurs_occupes:
            # On ne déploie un radar que si on en a les moyens et que ce n'est pas un secteur qu'on vient de condamner
            if sect < len(alertes_vers) and alertes_vers[sect] == "INCONNU" and sect not in secteurs_condamnes:
                if mon_budget >= PRIX_ORNI and self.envoyer_action(f"AJOUTERORNI|{sect}"):
                    print(f"  [VISION] Radar déployé Secteur {sect}")
                    mon_budget -= PRIX_ORNI

        # --- PHASE 4 : HEAT MAP ---
        heatmap = self.generer_heatmap(alertes_vers, ennemis, usines_actives, secteurs_condamnes)

        # --- PHASE 5 : MIGRATION DES RECOLTEUSES ---
        for l, c in mes_unites:
            if self.actions_restantes <= 0: break
            densite = self.plateau[(l, c)]['densite']
            partage = any(distance(l, c, el, ec) == 0 for el, ec in ennemis)
            
            # Si le sol est asséché ou volé par un ennemi
            if densite <= 1 or partage:
                if heatmap:
                    cible = heatmap.pop(0)
                    if self.envoyer_action(f"DEPLACER|{l}|{c}|{cible['l']}|{cible['c']}"):
                        print(f"  [MIGRATION] Transfert vers spot opti en ({cible['l']},{cible['c']})")

        # --- PHASE 6 : EXPANSION ET CONSTRUCTION ---
        if tour_actuel < 185: 
            while self.actions_restantes > 0 and heatmap:
                cible = heatmap.pop(0)
                
                est_proche_ennemi = any(distance(cible['l'], cible['c'], el, ec) <= 1 for el, ec in ennemis)
                est_proche_usine = any(distance(cible['l'], cible['c'], ul, uc) <= 2 for ul, uc in usines_actives)
                
                # RÈGLE DE L'USINE : Si on est super riche, on pose une usine sur le meilleur spot
                if mon_budget >= PRIX_USINE and len(mes_unites) >= 5 and not est_proche_usine:
                    self.envoyer(f"AJOUTERUSINE|{cible['l']}|{cible['c']}")
                    self.actions_restantes -= 1
                    
                    refuse = False
                    for msg in self.lire_reseau(0.05):
                        if msg.startswith("NOK"): refuse = True
                    
                    if refuse: 
                        break # Fin des achats si on est à sec
                    else:
                        print(f"  [INDUSTRIE] Usine construite en ({cible['l']},{cible['c']})")
                        mon_budget -= PRIX_USINE
                        continue # On passe au spot suivant

                # RÈGLE DE LA RÉCOLTEUSE : Sinon on achète des récolteuses
                if not est_proche_ennemi or est_proche_usine:
                    self.envoyer(f"AJOUTERRECOLTEUSE|{cible['l']}|{cible['c']}")
                    self.actions_restantes -= 1
                    
                    refuse = False
                    for msg in self.lire_reseau(0.05):
                        if msg.startswith("NOK"): refuse = True
                    
                    if refuse:
                        break # On stoppe dès que le banquier dit non
                    else:
                        print(f"  [ACHAT] Récolteuse déployée en ({cible['l']},{cible['c']})")
                        mon_budget -= PRIX_RECOLTEUSE

if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "Equipe_ESEO"
    bot = SpiceBotEsport(equipe=nom_equipe)
    try: bot.connecter()
    except KeyboardInterrupt: print("\n[!] Fin du programme.")