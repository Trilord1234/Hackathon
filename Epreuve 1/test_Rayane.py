import socket

HOST = "127.0.0.1" # serveur ip port
PORT = 1234

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((HOST, PORT)) # connection   serv

def envoyer(commande):
    s.sendall((commande + "\n").encode())
    return s.recv(4096).decode().strip()


msg = s.recv(4096).decode().strip()  # recoit message du serveur
print(msg)                             # print le message du serv
reponse = envoyer("ESEOctet")       # envoie votre nom
print(reponse)                        # reçoit "Bonjour MonEquipe vous êtes l'équipe |X"

# Boucle de jeu
while True:
    msg = s.recv(4096).decode().strip()
    '''
    verifier la map lorsque on est pas en jeu
    '''
    envoyer("ELEMENTS")
    envoyer("DENSITE")


    if msg.startswith("DEBUT_TOUR"):
        tour = msg.split("|")[1]
        print(f"Tour {tour}")

        #### A UTILISER POUR DENISTE UNE SEULE FOIS DANS LE JEU
        if densite is None:  # une seule fois au tour 1
            densite = envoyer("DENSITE")

        # Vos actions ici
        envoyer("DENSITE")
        envoyer("ELEMENTS")
        envoyer("WARNING")
        envoyer("FINDETOUR")  # toujours terminer le tour !





elements = envoyer("ELEMENTS")

def trouver_case_libre(elements):
    for i in range(288):
        if elements[i] == 'X':
            return (i // 18, i % 18)
    return None

# Déplacer votre récolteuse vers une case libre
case_libre = trouver_case_libre(elements)
if case_libre:
    ligne_dest, col_dest = case_libre
    envoyer(f"DEPLACER|{ligne_actuelle}|{col_actuelle}|{ligne_dest}|{col_dest}")



def trouver_case_libre_hors_secteur(elements, secteur):
    for i in range(288):
        if elements[i] == 'X':
            ligne = i // 18
            col = i % 18
            # Vérifier que la case n'est pas dans le secteur dangereux
            if secteur == 0 and (ligne > 7 or col > 8):
                return (ligne, col)
            if secteur == 1 and (ligne > 7 or col < 9):
                return (ligne, col)
            if secteur == 2 and (ligne < 8 or col > 8):
                return (ligne, col)
            if secteur == 3 and (ligne < 8 or col < 9):
                return (ligne, col)
    return None




