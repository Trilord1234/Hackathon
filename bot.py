import socket
import select
import sys
import random

# --- CONSTANTES ---
HAUTEUR, LARGEUR = 16, 18
MAX_ACTIONS = 15
PRIX_RECOLTEUSE = 3000
PRIX_USINE = 5000
PRIX_ORNI = 400
PRIX_SABOTAGE = 600

def get_secteur(l, c):
    return (0 if c <= 8 else 1) if l <= 7 else (2 if c <= 8 else 3)

def distance(l1, c1, l2, c2):
    return max(abs(l1 - l2), abs(c1 - c2))

class SpiceBotMaster:
    def __init__(self, equipe="Kwisatz_Haderach"):
        self.equipe = equipe
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.mon_id = -1
        self._buffer = ""
        self.actions_restantes = MAX_ACTIONS
        self.plateau = {}
        
        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                self.plateau[(l, c)] = {'densite': 0, 'element': 'X', 'secteur': get_secteur(l, c)}

    # ── 1. RÉSEAU SYNCHRONE BLINDÉ ───────────────────────────────────────────
    
    def connecter(self):
        print(f"[*] Démarrage IA Master v3 (Anti-Crash) : {self.equipe}...")
        self.sock.connect(("127.0.0.1", 1234))
        while True:
            for msg in self.lire_reseau(0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    parties = msg.split('|')
                    if len(parties) > 1:
                        self.mon_id = int(parties[1].strip())
                        print(f"[+] Authentifié ! ID : {self.mon_id}")
                        self.boucle_jeu()
                        return

    def envoyer(self, cmd):
        self.sock.sendall((cmd + "\n").encode('utf-8'))

    def envoyer_action(self, cmd):
        # Le garde-fou ultime : impossible de spammer le serveur
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
                if "DEBUT_TOUR" in msg or msg == "OK" or msg.startswith("NOK"): continue 
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288: return msg
                elif cmd == "WARNING" and "|" in msg: return msg
                elif cmd == "SCORES" and any(c.isdigit() for c in msg): return msg
            tentatives += 1
            
        if cmd == "WARNING": return "INCONNU|INCONNU|INCONNU|INCONNU"
        if cmd == "SCORES": return "0|0|0|0"
        return "X" * 288 

    # ── 2. HEAT MAP (Moteur Tactique) ────────────────────────────────────────
    
    def generer_heatmap(self, alertes_vers, ennemis, mes_unites, usines_ennemies, secteurs_condamnes, phase):
        scores_cases = []
        ennemis_par_sect = {0:0, 1:0, 2:0, 3:0}
        allies_par_sect = {0:0, 1:0, 2:0, 3:0}
        
        for el, ec in ennemis: ennemis_par_sect[get_secteur(el, ec)] += 1
        for ml, mc in mes_unites: allies_par_sect[get_secteur(ml, mc)] += 1

        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                data = self.plateau[(l, c)]
                if data['element'] != 'X': continue # Strictement vide
                
                sect = data['secteur']
                if alertes_vers[sect] == "DANGER" or sect in secteurs_condamnes: continue

                score = data['densite'] * 10
                if score <= 0: continue

                # TACTIQUE : Voler le bonus des usines
                if any(distance(l, c, ul, uc) <= 2 for ul, uc in usines_ennemies):
                    score *= 3

                # TACTIQUE : Anti-Clustering (Disperser pour survivre)
                if allies_par_sect[sect] >= 4:
                    score -= 100 

                # TACTIQUE : Bait (Laisser les ennemis s'entasser)
                if ennemis_par_sect[sect] > 0:
                    score -= (ennemis_par_sect[sect] * 10)

                scores_cases.append({'l': l, 'c': c, 'score': score, 'sect': sect})
        
        random.shuffle(scores_cases) 
        scores_cases.sort(key=lambda x: x['score'], reverse=True)
        return scores_cases

    # ── 3. BOUCLE DE SYNCHRONISATION ─────────────────────────────────────────
    
    def boucle_jeu(self):
        tour_actuel = 0
        while True:
            for msg in self.lire_reseau(0.1):
                if msg.startswith("DEBUT_TOUR"):
                    try: tour_actuel = int(msg.split('|')[1])
                    except: pass
                    
                    phase = "EARLY"
                    if tour_actuel > 50: phase = "MID"
                    if tour_actuel > 175: phase = "LATE"
                    
                    print(f"\n{'='*12} TOUR {tour_actuel} [{phase}] {'='*12}")
                    self.actions_restantes = MAX_ACTIONS
                    
                    # Consommation des actions pour Scanner
                    rep_densite = self.requete("DENSITE")
                    self.actions_restantes -= 1
                    rep_elements = self.requete("ELEMENTS")
                    self.actions_restantes -= 1
                    
                    # Failsafe Split : Empêche le crash si le serveur coupe la chaîne
                    raw_warning = self.requete("WARNING")
                    alertes_vers = (raw_warning + "|INCONNU|INCONNU|INCONNU").split('|')[:4]
                    self.actions_restantes -= 1
                    
                    raw_scores = self.requete("SCORES")
                    scores_bruts = (raw_scores + "|0|0|0|0").split('|')
                    self.actions_restantes -= 1
                    
                    mon_budget = 0
                    try:
                        if 0 <= self.mon_id < len(scores_bruts):
                            mon_budget = int(scores_bruts[self.mon_id])
                        else: mon_budget = int(scores_bruts[0])
                    except: pass

                    print(f"[*] Trésorerie : {mon_budget} | Actions Restantes : {self.actions_restantes}")

                    for i in range(HAUTEUR * LARGEUR):
                        l, c = divmod(i, LARGEUR)
                        self.plateau[(l, c)]['densite'] = int(rep_densite[i]) if rep_densite[i].isdigit() else 0
                        self.plateau[(l, c)]['element'] = rep_elements[i]

                    self.jouer_tour(alertes_vers, tour_actuel, phase, mon_budget)
                    self.envoyer("FINDETOUR")

    def jouer_tour(self, alertes_vers, tour_actuel, phase, mon_budget):
        mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
        ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
        usines_actives = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'U']

        # Démographie et SCANNER DE BOURDES (Anti-Stacking)
        secteurs_condamnes = set()
        ennemis_par_sect = {0:0, 1:0, 2:0, 3:0}
        allies_par_sect = {0:0, 1:0, 2:0, 3:0}
        allies_sur_case = {} # Le détecteur de collision
        
        for el, ec in ennemis: ennemis_par_sect[get_secteur(el, ec)] += 1
        for ml, mc in mes_unites: 
            allies_par_sect[get_secteur(ml, mc)] += 1
            allies_sur_case[(ml, mc)] = allies_sur_case.get((ml, mc), 0) + 1

        # --- PHASE 1 : SABOTAGE ET TERRE BRÛLÉE ---
        if phase != "EARLY": 
            for sect in range(4):
                if alertes_vers[sect] == "DANGER": continue
                if phase == "LATE" and ennemis_par_sect[sect] >= 1 and allies_par_sect[sect] == 0:
                    if mon_budget >= PRIX_SABOTAGE and self.envoyer_action(f"SABOTER|{sect}"):
                        print(f"  [TERRE BRÛLÉE] 💥 Harcèlement Secteur {sect}")
                        mon_budget -= PRIX_SABOTAGE
                        secteurs_condamnes.add(sect)
                elif ennemis_par_sect[sect] >= 3 and allies_par_sect[sect] <= 1:
                    if mon_budget >= PRIX_SABOTAGE and self.envoyer_action(f"SABOTER|{sect}"):
                        print(f"  [KAMIKAZE] 💥 Frappe Majeure Secteur {sect}")
                        mon_budget -= PRIX_SABOTAGE
                        secteurs_condamnes.add(sect)

        # --- PHASE 2 : HEAT MAP (Calculée après les condamnations) ---
        heatmap = self.generer_heatmap(alertes_vers, ennemis, mes_unites, usines_actives, secteurs_condamnes, phase)

        # --- PHASE 3 : SURVIE NATIVE (Fini Maps.py, zéro crash garanti) ---
        for l, c in mes_unites:
            if self.actions_restantes <= 0: break
            sect = get_secteur(l, c)
            if alertes_vers[sect] == "DANGER":
                if heatmap:
                    cible = heatmap.pop(0) # Impossible de cibler 2 fois la même case
                    if self.envoyer_action(f"DEPLACER|{l}|{c}|{cible['l']}|{cible['c']}"):
                        print(f"  [SURVIE] Fuite validée vers ({cible['l']},{cible['c']})")
                        allies_sur_case[(l, c)] -= 1 # Mise à jour locale

        # --- PHASE 4 : VISION (Radars) ---
        for sect in {get_secteur(l, c) for l, c in mes_unites}:
            if sect < len(alertes_vers) and alertes_vers[sect] == "INCONNU" and sect not in secteurs_condamnes:
                if mon_budget >= PRIX_ORNI and self.envoyer_action(f"AJOUTERORNI|{sect}"):
                    print(f"  [VISION] Radar activé Secteur {sect}")
                    mon_budget -= PRIX_ORNI

        # --- PHASE 5 : CORRECTION DES BOURDES & MIGRATION ---
        for l, c in mes_unites:
            if self.actions_restantes <= 0: break
            densite = self.plateau[(l, c)]['densite']
            partage_ennemi = any(distance(l, c, el, ec) == 0 for el, ec in ennemis)
            surcharge_alliee = allies_sur_case.get((l, c), 0) > 1 # VÉRIFICATION DE BOURDE ICI
            
            # Si la case est pauvre, ou volée, ou si on est empilé bêtement sur nous-mêmes
            if densite <= 1 or partage_ennemi or surcharge_alliee:
                if heatmap:
                    cible = heatmap.pop(0)
                    if self.envoyer_action(f"DEPLACER|{l}|{c}|{cible['l']}|{cible['c']}"):
                        if surcharge_alliee:
                            print(f"  [ANTI-BOURDE] Dé-collage d'unité ! Transfert vers ({cible['l']},{cible['c']})")
                        else:
                            print(f"  [MIGRATION] Repositionnement sur ({cible['l']},{cible['c']})")
                        allies_sur_case[(l, c)] -= 1

        # --- PHASE 6 : EXPANSION ---
        if phase != "LATE": 
            while self.actions_restantes > 0 and heatmap:
                cible = heatmap.pop(0)
                
                # R.O.I. de l'Usine
                if len(mes_unites) >= 4 and phase == "EARLY" and mon_budget >= PRIX_USINE:
                    allies_a_portee = sum(1 for ml, mc in mes_unites if distance(ml, mc, cible['l'], cible['c']) <= 2)
                    tours_restants = 200 - tour_actuel
                    roi = (allies_a_portee * 3 * 10 * tours_restants) - PRIX_USINE
                    
                    if roi > 2000 and allies_a_portee >= 2:
                        if self.envoyer_action(f"AJOUTERUSINE|{cible['l']}|{cible['c']}"):
                            print(f"  [INDUSTRIE] Usine bâtie en ({cible['l']},{cible['c']})")
                            mon_budget -= PRIX_USINE
                            continue 

                # Achat de Récolteuse
                est_proche_ennemi = any(distance(cible['l'], cible['c'], el, ec) <= 1 for el, ec in ennemis)
                est_proche_usine = any(distance(cible['l'], cible['c'], ul, uc) <= 2 for ul, uc in usines_actives)
                
                if mon_budget >= PRIX_RECOLTEUSE:
                    if not est_proche_ennemi or est_proche_usine:
                        if self.envoyer_action(f"AJOUTERRECOLTEUSE|{cible['l']}|{cible['c']}"):
                            print(f"  [ACHAT] Unité déployée en ({cible['l']},{cible['c']})")
                            mon_budget -= PRIX_RECOLTEUSE
                else:
                    break 

if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "Equipe_ESEO"
    bot = SpiceBotMaster(equipe=nom_equipe)
    try: bot.connecter()
    except KeyboardInterrupt: print("\n[!] Fin.")