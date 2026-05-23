#!/usr/bin/env python3
"""
For The Spice - IA Elite
Connexion TCP non-bloquante avec buffer robuste + reconnexion automatique
"""

import socket
import select
import sys
import time
import logging
from brain import Brain

# En compétition: WARNING seulement pour économiser le temps I/O
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ia.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

TEAM_NAME = "SpiceHunter"
HOST = "127.0.0.1"
PORT = 1234
<<<<<<< Updated upstream
=======
<<<<<<< HEAD

MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 2.0  # secondes
=======
>>>>>>> f2a5c98b7dc9835c553043c2fc2fecf1ba13aaa2
>>>>>>> Stashed changes


class NetworkClient:
    """Gestion réseau robuste avec buffer et select() non-bloquant."""

    def __init__(self):
        self.sock = None
        self._buffer = ""
        self.host = None
        self.port = None

    def connect(self, host, port):
        self.host = host
        self.port = port
        self._do_connect()

    def _do_connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        log.warning(f"Connecté à {self.host}:{self.port}")

    def _reconnect(self):
        """Tentative de reconnexion avec backoff."""
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            log.warning(f"Reconnexion tentative {attempt}/{MAX_RECONNECT_ATTEMPTS}...")
            try:
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                self._buffer = ""
                self._do_connect()
                log.warning("Reconnexion réussie !")
                return True
            except Exception as e:
                log.warning(f"Échec reconnexion: {e}")
                time.sleep(RECONNECT_DELAY * attempt)
        return False

    def send(self, msg):
        try:
            self.sock.sendall((msg + '\n').encode('utf-8'))
            log.debug(f"→ {msg!r}")
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            log.warning(f"Erreur envoi: {e}")
            if self._reconnect():
                self.sock.sendall((msg + '\n').encode('utf-8'))

    def read_lines(self, timeout=0.05):
        """Lit toutes les lignes disponibles (non-bloquant via select)."""
        try:
            ready, _, _ = select.select([self.sock], [], [], timeout)
            if ready:
                data = self.sock.recv(8192).decode('utf-8')
                if not data:
                    raise ConnectionError("Connexion fermée par le serveur")
                self._buffer += data
        except (ConnectionError, OSError) as e:
            log.warning(f"Erreur lecture: {e}")
            return []

        lines = []
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            line = line.strip()
            if line:
                lines.append(line)
        return lines

    def request(self, cmd):
        """Envoie une demande et attend la réponse (hors DEBUT_TOUR/OK/NOK)."""
        self.send(cmd)
        for _ in range(100):
            for msg in self.read_lines(0.03):
                log.debug(f"← {msg!r}")
                if msg.startswith("DEBUT_TOUR") or msg in ("OK",):
                    continue
                if msg.startswith("NOK"):
                    log.warning(f"NOK sur {cmd}: {msg}")
                    continue
                if cmd == "DENSITE" and len(msg) >= 288:
                    return msg
                if cmd == "ELEMENTS" and len(msg) >= 288:
                    return msg
                if cmd == "WARNING" and '|' in msg:
                    return msg
                if cmd == "SCORES" and any(ch.isdigit() for ch in msg):
                    return msg
        # Fallbacks sûrs
        if cmd == "WARNING":  return "INCONNU|INCONNU|INCONNU|INCONNU"
        if cmd == "SCORES":   return "0|0|0|0"
        return 'X' * 288

    def send_action(self, cmd):
        """Envoie une action et lit la réponse OK/NOK."""
        self.send(cmd)
        for _ in range(50):
            for msg in self.read_lines(0.02):
                log.debug(f"← {msg!r}")
                if msg == "OK":
                    return True
                if msg.startswith("NOK"):
                    log.warning(f"Action refusée [{cmd}]: {msg}")
                    return False
        return False


def main():
    team_name = sys.argv[1] if len(sys.argv) > 1 else TEAM_NAME
    log.warning(f"=== IA For The Spice | Équipe: {team_name} ===")

    net = NetworkClient()
    net.connect(HOST, PORT)

    player_id = -1

    # Handshake
    while player_id == -1:
        for msg in net.read_lines(0.5):
            log.debug(f"← {msg!r}")
            if msg == "NOM_EQUIPE":
                net.send(team_name)
<<<<<<< Updated upstream
            elif "quipe" in msg and "|" in msg and not msg.startswith("DEBUT_TOUR"):
                # "Vous êtes l'équipe|1"
=======
<<<<<<< HEAD
            elif "équipe" in msg or "equipe" in msg.lower() or "|" in msg:
=======
            elif "quipe" in msg and "|" in msg and not msg.startswith("DEBUT_TOUR"):
                # "Vous êtes l'équipe|1"
>>>>>>> f2a5c98b7dc9835c553043c2fc2fecf1ba13aaa2
>>>>>>> Stashed changes
                try:
                    player_id = int(msg.split('|')[-1].strip())
                    log.warning(f"Inscrit ! Player ID: {player_id}")
                except ValueError:
                    pass

    brain = Brain(player_id, team_name, net)

    # Boucle principale
    while True:
        try:
            for msg in net.read_lines(0.1):
                if msg.startswith("DEBUT_TOUR|"):
                    turn = int(msg.split('|')[1])
                    log.warning(f"\n{'='*14} TOUR {turn} {'='*14}")
                    brain.play_turn(turn)
        except (ConnectionError, OSError) as e:
            log.warning(f"Connexion perdue: {e}")
            if not net._reconnect():
                log.warning("Impossible de se reconnecter. Abandon.")
                sys.exit(1)
            # Après reconnexion, envoyer le nom d'équipe à nouveau
            net.send(team_name)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("IA arrêtée manuellement.")
    except Exception as e:
        log.warning(f"Erreur fatale: {e}")
        sys.exit(1)
