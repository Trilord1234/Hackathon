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

        # Vos actions ici
        envoyer("DENSITE")
        envoyer("ELEMENTS")
        envoyer("WARNING")
        envoyer("FINDETOUR")  # toujours terminer le tour !