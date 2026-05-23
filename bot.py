import socket
import select
import sys
import random
import Maps

# --- CONSTANTES ---
HAUTEUR, LARGEUR = 16, 18
MAX_ACTIONS = 15
PRIX_RECOLTEUSE = 3000
PRIX_USINE = 5000
PRIX_ORNI = 400
PRIX_SABOTAGE = 500

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

    # ── 1. RÉSEAU BLINDÉ ─────────────────────────────────────────────────────
    
    def connecter(self):
        print(f"[*] Démarrage de l'IA Master : {self.equipe}...")
        self.sock.connect(("127.0.0.1", 1234))
        while True:
            for msg in self.lire_reseau(0.1):
                if msg == "NOM_EQUIPE":
                    self.envoyer(self.equipe)
                elif "êtes l'équipe" in msg:
                    parties = msg.split('|')
                    if len(parties) > 1:
                        self.mon_id = int(parties[1].strip())
                        print(f"[+] Authentifié ! Mon ID : {self.mon_id}")
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
                if "DEBUT_TOUR" in msg or msg == "OK" or msg.startswith("NOK"): continue 
                if cmd in ["DENSITE", "ELEMENTS"] and len(msg) >= 288: return msg
                elif cmd == "WARNING" and "|" in msg: return msg
                elif cmd == "SCORES" and any(c.isdigit() for c in msg): return msg
            tentatives += 1
            
        if cmd == "WARNING": return "INCONNU|INCONNU|INCONNU|INCONNU"
        if cmd == "SCORES": return "0|0|0|0"
        return "X" * 288 

    # ── 2. LE CERVEAU QUANTITATIF (HEAT MAP) ─────────────────────────────────
    
    def generer_heatmap(self, alertes_vers, ennemis, mes_unites, usines_ennemies, secteurs_condamnes, phase):
        scores_cases = []
        
        ennemis_par_sect = {0:0, 1:0, 2:0, 3:0}
        allies_par_sect = {0:0, 1:0, 2:0, 3:0}
        for el, ec in ennemis: ennemis_par_sect[get_secteur(el, ec)] += 1
        for ml, mc in mes_unites: allies_par_sect[get_secteur(ml, mc)] += 1

        for l in range(HAUTEUR):
            for c in range(LARGEUR):
                data = self.plateau[(l, c)]
                if data['element'] != 'X': continue
                
                sect = data['secteur']
                if alertes_vers[sect] == "DANGER" or sect in secteurs_condamnes: continue

                # Rentabilité de base
                score = data['densite'] * 10
                if score <= 0: continue

                # TACTIQUE : Diviser pour Mieux Régner (Anti-Clustering)
                # Si on a trop d'unités ici, on met un malus massif pour forcer l'expansion ailleurs
                if allies_par_sect[sect] >= 4:
                    score -= 200 

                # TACTIQUE : Parasitisme (Vampiriser le x2 ennemi)
                if any(distance(l, c, ul, uc) <= 2 for ul, uc in usines_ennemies):
                    if phase == "MID": score *= 3 # Au milieu du jeu, c'est ultra rentable
                    else: score *= 2

                # TACTIQUE : Le Piège à Vers (Bait)
                # S'il y a des ennemis, on baisse l'attrait pour nous, on les laisse s'entasser
                if ennemis_par_sect[sect] > 0:
                    score -= (ennemis_par_sect[sect] * 10)

                scores_cases.append({'l': l, 'c': c, 'score': score, 'sect': sect})
        
        random.shuffle(scores_cases) 
        scores_cases.sort(key=lambda x: x['score'], reverse=True)
        return scores_cases

    # ── 3. BOUCLE ET SYNCHRONISATION ─────────────────────────────────────────
    
    def boucle_jeu(self):
        tour_actuel = 0
        while True:
            for msg in self.lire_reseau(0.1):
                if msg.startswith("DEBUT_TOUR"):
                    try: tour_actuel = int(msg.split('|')[1])
                    except: pass
                    
                    # Détermination de la Phase
                    phase = "EARLY"
                    if tour_actuel > 60: phase = "MID"
                    if tour_actuel > 160: phase = "LATE"
                    
                    print(f"\n{'='*12} TOUR {tour_actuel} [{phase} GAME] {'='*12}")
                    
                    self.actions_restantes = MAX_ACTIONS
                    
                    # 4 Requêtes = 4 Actions consommées
                    rep_densite = self.requete("DENSITE")
                    self.actions_restantes -= 1
                    rep_elements = self.requete("ELEMENTS")
                    self.actions_restantes -= 1
                    alertes_vers = self.requete("WARNING").split('|')
                    self.actions_restantes -= 1
                    scores_bruts = self.requete("SCORES").split('|')
                    self.actions_restantes -= 1
                    
                    for i in range(HAUTEUR * LARGEUR):
                        l, c = divmod(i, LARGEUR)
                        self.plateau[(l, c)]['densite'] = int(rep_densite[i]) if rep_densite[i].isdigit() else 0
                        self.plateau[(l, c)]['element'] = rep_elements[i]
                        try:
                            Maps.maps['obj'][l][c] = rep_elements[i]
                            Maps.maps['dns'][l][c] = rep_densite[i]
                        except: pass 

                    self.jouer_tour(alertes_vers, tour_actuel, phase)
                    self.envoyer("FINDETOUR")

    def jouer_tour(self, alertes_vers, tour_actuel, phase):
        mes_unites = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == str(self.mon_id)]
        ennemis = [(l, c) for (l, c), d in self.plateau.items() if d['element'] in ['0','1','2','3'] and d['element'] != str(self.mon_id)]
        usines_actives = [(l, c) for (l, c), d in self.plateau.items() if d['element'] == 'U']

        secteurs_condamnes = set()
        ennemis_par_sect = {0:0, 1:0, 2:0, 3:0}
        allies_par_sect = {0:0, 1:0, 2:0, 3:0}
        for el, ec in ennemis: ennemis_par_sect[get_secteur(el, ec)] += 1
        for ml, mc in mes_unites: allies_par_sect[get_secteur(ml, mc)] += 1

        # --- PRIORITÉ 1 : SURVIE (Maps.py) ---
        try:
            ordres_evac = Maps.evacuation_protocol(Maps.maps, self.mon_id, alertes_vers)
            for ordre in ordres_evac:
                if self.envoyer_action(f"DEPLACER|{ordre['orig_y']}|{ordre['orig_x']}|{ordre['dest_y']}|{ordre['dest_x']}"):
                    print(f"  [SURVIE] Fuite validée vers ({ordre['dest_y']},{ordre['dest_x']})")
        except: pass

        # --- PRIORITÉ 2 : GUERRE ET SABOTAGE ---
        if phase != "EARLY": # On ne sabote pas au début, on garde notre argent pour grandir
            for sect in range(4):
                if alertes_vers[sect] == "DANGER": continue
                
                # Le Sacrifice Kamikaze : Si l'ennemi a 3 unités et nous 1 (ou 0), on fait péter le secteur.
                # On perd 3500 (unité + tir) pour détruire 9000. Rentabilité énorme.
                if ennemis_par_sect[sect] >= 3 and allies_par_sect[sect] <= 1:
                    if self.envoyer_action(f"SABOTER|{sect}"):
                        print(f"  [KAMIKAZE] 💥 Frappe sur Secteur {sect} ! (Victimes ennemies: {ennemis_par_sect[sect]})")
                        secteurs_condamnes.add(sect)
                
                # Sabotage classique : Si 2 ennemis et 0 allié
                elif ennemis_par_sect[sect] >= 2 and allies_par_sect[sect] == 0:
                    if self.envoyer_action(f"SABOTER|{sect}"):
                        print(f"  [ASSASSINAT] 💥 Frappe sur Secteur {sect} (Victimes: {ennemis_par_sect[sect]})")
                        secteurs_condamnes.add(sect)

        # --- PRIORITÉ 3 : VISION (Radars) ---
        for sect in {get_secteur(l, c) for l, c in mes_unites}:
            if sect < len(alertes_vers) and alertes_vers[sect] == "INCONNU" and sect not in secteurs_condamnes:
                # La "Sonde d'achat" : On tente, si ça rate, on ignore.
                self.envoyer(f"AJOUTERORNI|{sect}")
                self.actions_restantes -= 1
                for msg in self.lire_reseau(0.05):
                    if msg == "OK": print(f"  [VISION] Radar Secteur {sect} OK")

        # --- PRIORITÉ 4 : HEAT MAP & MOBILITÉ ---
        heatmap = self.generer_heatmap(alertes_vers, ennemis, mes_unites, usines_actives, secteurs_condamnes, phase)

        for l, c in mes_unites:
            if self.actions_restantes <= 0: break
            densite = self.plateau[(l, c)]['densite']
            partage = any(distance(l, c, el, ec) == 0 for el, ec in ennemis)
            
            # Essaim : Quitter la case si elle est asséchée
            if densite <= 1 or partage:
                if heatmap:
                    cible = heatmap.pop(0)
                    if self.envoyer_action(f"DEPLACER|{l}|{c}|{cible['l']}|{cible['c']}"):
                        print(f"  [MIGRATION] Migration vers spot opti ({cible['l']},{cible['c']})")

        # --- PRIORITÉ 5 : GESTION DE L'INDUSTRIE ET EXPANSION ---
        if phase != "LATE": 
            while self.actions_restantes > 0 and heatmap:
                cible = heatmap.pop(0)
                
                # 5A. CALCUL DU R.O.I. POUR LES USINES
                # Si on a 5 unités, on regarde si ça vaut le coup de construire une usine
                if len(mes_unites) >= 5 and phase == "EARLY":
                    # Combien d'alliés à portée (<=2) du meilleur spot ?
                    allies_a_portee = sum(1 for ml, mc in mes_unites if distance(ml, mc, cible['l'], cible['c']) <= 2)
                    tours_restants = 200 - tour_actuel
                    
                    # Formule d'Espérance: (Nombre_Unités * Densité_Moyenne_3 * 10_épices * Tours) - Prix(5000)
                    roi = (allies_a_portee * 3 * 10 * tours_restants) - PRIX_USINE
                    
                    if roi > 2000 and allies_a_portee >= 2:
                        self.envoyer(f"AJOUTERUSINE|{cible['l']}|{cible['c']}")
                        self.actions_restantes -= 1
                        refuse = False
                        for msg in self.lire_reseau(0.05):
                            if msg.startswith("NOK"): refuse = True
                        if not refuse:
                            print(f"  [INDUSTRIE] Usine bâtie en ({cible['l']},{cible['c']}) - ROI espéré: {roi}")
                            continue # On passe au spot suivant

                # 5B. EXPANSION (Récolteuses)
                est_proche_ennemi = any(distance(cible['l'], cible['c'], el, ec) <= 1 for el, ec in ennemis)
                est_proche_usine_ennemie = any(distance(cible['l'], cible['c'], ul, uc) <= 2 for ul, uc in usines_actives)
                
                if not est_proche_ennemi or est_proche_usine_ennemie:
                    self.envoyer(f"AJOUTERRECOLTEUSE|{cible['l']}|{cible['c']}")
                    self.actions_restantes -= 1
                    refuse = False
                    for msg in self.lire_reseau(0.05):
                        if msg.startswith("NOK"): refuse = True
                    
                    if refuse: break # Compte en banque vide, on stoppe les achats
                    else: print(f"  [ACHAT] Déploiement en ({cible['l']},{cible['c']})")

if __name__ == "__main__":
    nom_equipe = sys.argv[1] if len(sys.argv) > 1 else "Equipe_ESEO"
    bot = SpiceBotMaster(equipe=nom_equipe)
    try: bot.connecter()
    except KeyboardInterrupt: print("\n[!] Fin du programme.")