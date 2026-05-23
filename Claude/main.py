#!/usr/bin/env python3
"""
For The Spice - IA Elite
Connexion TCP non-bloquante avec buffer robuste
"""

import socket
import select
import sys
import logging
from brain import Brain

logging.basicConfig(
    level=logging.INFO,
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


class NetworkClient:
    """Gestion réseau robuste avec buffer et select() non-bloquant."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._buffer = ""

    def connect(self, host, port):
        self.sock.connect((host, port))
        log.info(f"Connecté à {host}:{port}")

    def send(self, msg):
        self.sock.sendall((msg + '\n').encode('utf-8'))
        log.debug(f"→ {msg!r}")

    def read_lines(self, timeout=0.05):
        """Lit toutes les lignes disponibles (non-bloquant via select)."""
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if ready:
            data = self.sock.recv(8192).decode('utf-8')
            if not data:
                raise ConnectionError("Connexion fermée par le serveur")
            self._buffer += data
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
                # Ignorer les messages de contrôle
                if msg.startswith("DEBUT_TOUR") or msg in ("OK",):
                    continue
                if msg.startswith("NOK"):
                    log.warning(f"NOK sur {cmd}: {msg}")
                    continue
                # Réponses attendues selon la commande
                if cmd == "DENSITE" and len(msg) >= 288:
                    return msg
                if cmd == "ELEMENTS" and len(msg) >= 288:
                    return msg
                if cmd == "WARNING" and '|' in msg:
                    return msg
                if cmd == "SCORES" and any(ch.isdigit() for ch in msg):
                    return msg
        # Fallbacks
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
    log.info(f"=== IA For The Spice | Équipe: {team_name} ===")

    net = NetworkClient()
    net.connect(HOST, PORT)

    player_id = -1

    # Handshake
    while player_id == -1:
        for msg in net.read_lines(0.5):
            log.debug(f"← {msg!r}")
            if msg == "NOM_EQUIPE":
                net.send(team_name)
            elif "équipe" in msg or "equipe" in msg.lower() or "|" in msg:
                try:
                    player_id = int(msg.split('|')[-1].strip())
                    log.info(f"Inscrit ! Player ID: {player_id}")
                except ValueError:
                    pass

    brain = Brain(player_id, team_name, net)

    # Boucle principale
    while True:
        for msg in net.read_lines(0.1):
            if msg.startswith("DEBUT_TOUR|"):
                turn = int(msg.split('|')[1])
                log.info(f"\n{'='*14} TOUR {turn} {'='*14}")
                brain.play_turn(turn)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("IA arrêtée manuellement.")
    except ConnectionError as e:
        log.error(f"Connexion perdue: {e}")
        sys.exit(1)
