import socket

# Paramètres de connexion
HOST = '127.0.0.1'
PORT = 1234

def main():
    print("Démarrage du client manuel For The Spice...")
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((HOST, PORT))
            print("Connecté au serveur avec succès !\n")
        except ConnectionRefusedError:
            print("Erreur : Impossible de se connecter. Le serveur est-il bien lancé ?")
            return

        while True:
            # On écoute ce que le serveur nous dit
            data = s.recv(4096).decode('utf-8').strip()
            if not data:
                print("Le serveur a fermé la connexion.")
                break
                
            print(f"\n[Serveur] {data}")
            
            # Gestion de l'inscription
            if data == "NOM_EQUIPE":
                team = input("-> Entrez le nom de votre équipe : ")
                s.sendall(f"{team}\n".encode('utf-8'))
                
            # Gestion de la boucle de jeu
            elif data.startswith("DEBUT_TOUR"):
                tour_num = data.split('|')[1] if '|' in data else "?"
                print(f"--- À TOUS LES POSTES : C'est votre tour ({tour_num}) ---")
                print("Tapez vos commandes (ex: DENSITE, AJOUTERRECOLTEUSE|5|5).")
                print("Tapez FINDETOUR pour passer au tour suivant.")
                
                command_count = 0
                while command_count < 15:
                    cmd = input(f"Commande {command_count + 1}/15 > ").strip()
                    if not cmd:
                        continue
                        
                    # Envoi de la commande
                    s.sendall(f"{cmd}\n".encode('utf-8'))
                    
                    # On attend la réponse immédiate du serveur (OK, NOK, ou les données)
                    response = s.recv(4096).decode('utf-8').strip()
                    print(f"   [Réponse] {response}")
                    
                    command_count += 1
                    
                    if cmd == "FINDETOUR":
                        break
                        
                if command_count == 15:
                    print("Limite de 15 commandes atteinte pour ce tour.")

if __name__ == "__main__":
    main()