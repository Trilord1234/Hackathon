#!/usr/bin/env python3
"""
For The Spice - IA Elite
Réseau TCP robuste : buffer ligne par ligne + file DEBUT_TOUR anti-perte de tour
"""

import socket
import sys
import time
import logging
from brain import Brain

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ia.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

TEAM_NAME             = "SpiceHunter"
HOST                  = "127.0.0.1"
PORT                  = 1234
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY       = 2.0


class NetworkClient:
    """
    Gestion réseau robuste.

    Principe clé : _readline() lit UNE ligne depuis le socket via buffer interne.
    Toute ligne DEBUT_TOUR reçue pendant request()/send_action() est mise en file
    (_pending) pour ne jamais être perdue entre deux lectures.
    """

    def __init__(self):
        self.sock = None
        self._buffer  = ""
        self._pending = []   # File de DEBUT_TOUR reçus hors séquence
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

    def reconnect(self):
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            log.warning(f"Reconnexion tentative {attempt}/{MAX_RECONNECT_ATTEMPTS}...")
            try:
                if self.sock:
                    try: self.sock.close()
                    except Exception: pass
                self._buffer  = ""
                self._pending = []
                self._do_connect()
                log.warning("Reconnexion réussie !")
                return True
            except Exception as e:
                log.warning(f"Échec reconnexion: {e}")
                time.sleep(RECONNECT_DELAY * attempt)
        return False

    # ── Couche bas niveau ──────────────────────────────────────────────────

    def _readline(self) -> str:
        """Lit exactement une ligne depuis le socket (bloquant, bufferisé)."""
        while '\n' not in self._buffer:
            data = self.sock.recv(4096).decode('utf-8')
            if not data:
                raise ConnectionError("Serveur déconnecté (EOF)")
            self._buffer += data
        line, self._buffer = self._buffer.split('\n', 1)
        return line.strip()

    def _send_raw(self, msg: str):
        """Envoie une ligne brute au serveur."""
        self.sock.sendall((msg + '\n').encode('utf-8'))
        log.debug(f"→ {msg!r}")

    # ── Couche protocole ───────────────────────────────────────────────────

    def request(self, cmd: str) -> str:
        """
        Envoie une demande de données (DENSITE / ELEMENTS / WARNING / SCORES)
        et retourne la réponse du serveur.

        Tout DEBUT_TOUR reçu pendant l'attente est mis en file _pending
        pour ne jamais être perdu.
        """
        self._send_raw(cmd)
        while True:
            line = self._readline()
            log.debug(f"← {line!r}")

            # DEBUT_TOUR reçu hors séquence → mise en file, on continue d'attendre
            if line.startswith('DEBUT_TOUR'):
                log.warning(f"[NET] DEBUT_TOUR hors-séquence, mis en file: {line}")
                self._pending.append(line)
                continue

            # Réponse NOK : retourner une valeur sûre
            if line.startswith('NOK'):
                log.warning(f"NOK sur {cmd}: {line}")
                if cmd == 'WARNING': return 'INCONNU|INCONNU|INCONNU|INCONNU'
                if cmd == 'SCORES':  return '0|0|0|0'
                return 'X' * 288

            # Validation de la réponse attendue
            if cmd == 'DENSITE'  and len(line) >= 288: return line
            if cmd == 'ELEMENTS' and len(line) >= 288: return line
            if cmd == 'WARNING'  and '|' in line:      return line
            if cmd == 'SCORES'   and any(ch.isdigit() for ch in line): return line

            # Réponse inattendue (OK résiduel, etc.) → ignorer et relire
            log.debug(f"[NET] Ligne ignorée pendant {cmd}: {line!r}")

    def send_action(self, cmd: str) -> bool:
        """
        Envoie une action de jeu (AJOUTERRECOLTEUSE, DEPLACER, etc.) et lit OK/NOK.
        Tout DEBUT_TOUR hors-séquence est mis en file.
        """
        self._send_raw(cmd)
        while True:
            line = self._readline()
            log.debug(f"← {line!r}")

            if line.startswith('DEBUT_TOUR'):
                log.warning(f"[NET] DEBUT_TOUR hors-séquence (action), mis en file: {line}")
                self._pending.append(line)
                continue

            if line == 'OK':
                return True
            if line.startswith('NOK'):
                log.warning(f"Action refusée [{cmd}]: {line}")
                return False

            # Ligne inattendue (réponse de données, etc.) → ignorer
            log.debug(f"[NET] Ligne inattendue pendant action {cmd}: {line!r}")

    def wait_for_turn(self) -> int:
        """
        Attend le prochain DEBUT_TOUR et retourne le numéro du tour.
        Draine d'abord la file _pending, puis lit le socket.
        Les OK/NOK résiduels (ex: FINDETOUR) sont ignorés silencieusement.
        """
        # Vider la file des DEBUT_TOUR reçus hors-séquence
        while self._pending:
            msg = self._pending.pop(0)
            if msg.startswith('DEBUT_TOUR|'):
                try:
                    return int(msg.split('|')[1])
                except (IndexError, ValueError):
                    pass

        # Attendre le prochain message du serveur
        while True:
            line = self._readline()
            if line.startswith('DEBUT_TOUR|'):
                try:
                    return int(line.split('|')[1])
                except (IndexError, ValueError):
                    pass
            # OK résiduel de FINDETOUR ou autre → ignorer
            log.debug(f"[NET] Ignoré dans wait_for_turn: {line!r}")

    def send_findetour(self):
        """Envoie FINDETOUR. La réponse OK sera drainée par wait_for_turn."""
        self._send_raw('FINDETOUR')


def main():
    team_name = sys.argv[1] if len(sys.argv) > 1 else TEAM_NAME
    log.warning(f"=== IA For The Spice | Équipe: {team_name} ===")

    net = NetworkClient()

    # Retry si le serveur n'est pas encore prêt
    for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
        try:
            net.connect(HOST, PORT)
            break
        except ConnectionRefusedError:
            if attempt == MAX_RECONNECT_ATTEMPTS:
                log.warning("Serveur introuvable. Abandon.")
                sys.exit(1)
            log.warning(f"Serveur pas prêt (tentative {attempt}). Retry dans {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)

    player_id = -1

    # ── Handshake ──────────────────────────────────────────────────────────
    while player_id == -1:
        line = net._readline()
        log.debug(f"← {line!r}")

        if line == 'NOM_EQUIPE':
            net._send_raw(team_name)

        elif 'quipe' in line and '|' in line and not line.startswith('DEBUT_TOUR'):
            # "Bonjour <nom> vous êtes l'équipe |<id>"
            try:
                player_id = int(line.split('|')[-1].strip())
                log.warning(f"Inscrit ! Player ID: {player_id}")
            except ValueError:
                log.warning(f"Impossible de parser l'ID depuis: {line!r}")

    brain = Brain(player_id, team_name, net)

    # ── Boucle principale ──────────────────────────────────────────────────
    while True:
        try:
            turn = net.wait_for_turn()
            log.warning(f"\n{'='*14} TOUR {turn} {'='*14}")
            brain.play_turn(turn)

        except (ConnectionError, OSError) as e:
            log.warning(f"Connexion perdue: {e}")
            if not net.reconnect():
                log.warning("Impossible de se reconnecter. Abandon.")
                sys.exit(1)
            # Après reconnexion, le serveur enverra NOM_EQUIPE de nouveau
            line = net._readline()
            if line == 'NOM_EQUIPE':
                net._send_raw(team_name)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("IA arrêtée manuellement.")
    except Exception as e:
        log.warning(f"Erreur fatale: {e}")
        raise
