import cmd
import time
import sys
from typing import Any, Optional, Dict

from shared_state import connect_ipc_manager, get_ipc_handles_from_manager


class DisplayState:
    """
    Gère l'affichage de l'état global de la simulation et la communication avec l'utilisateur

    """

    def __init__(self, mq_to_env: Any, mq_from_env: Any, refresh_period: float = 0.5) -> None:
        """
        Initialise l'état du display.

        Args:
            mq_to_env: File de messages (proxy manager) pour envoyer des commandes vers env.
            mq_from_env: File de messages (proxy manager) pour recevoir des messages provenant de env.
            refresh_period: Période (en secondes) entre deux rafraîchissements d'affichage.
        """
        self.mq_to_env = mq_to_env
        self.mq_from_env = mq_from_env
        self.refresh_period = refresh_period

        self.running = True
        self.last_snapshot: Optional[Dict[str, Any]] = None  # dernier état reçu depuis env
        self.last_render_time: float = 0.0


def display_main() -> None:
    """
    Point d'entrée du processus display.

    Initialise les mécanismes IPC, puis lance la boucle principale d'affichage
    et de contrôle utilisateur.
    """
    state = init_ipc()
    try:
        ui_loop(state)
    finally:
        cleanup(state)


def init_ipc() -> DisplayState:
    """
    Initialise et attache les mécanismes IPC nécessaires au display.

    Le display étant lancé séparément, il récupère les files de messages
    via le manager (connect_ipc_manager).

    Returns:
        Un objet DisplayState initialisé.
    """
    mgr = connect_ipc_manager()
    sem_mutex, sem_grass, sem_prey, q_to_env, q_from_env = get_ipc_handles_from_manager(mgr)

    # Le display n'utilise pas les sémaphores : on ne garde que les queues.
    return DisplayState(mq_to_env=q_to_env, mq_from_env=q_from_env, refresh_period=0.5)


def ui_loop(state: DisplayState) -> None:
    """
    Boucle principale du display.

    À chaque itération :
    - récupère et traite les messages en provenance de env,
    - lit et traite l'entrée utilisateur,
    - rafraîchit l'affichage périodiquement,
    - envoie les commandes correspondantes à env via la file de messages.
    """
    while state.running:
        # 1. Récupère et traite les messages de env
        poll_env_messages(state)

        # 2. Lit et traite l'entrée utilisateur (non bloquante)
        user_cmd = read_user_command()
        if user_cmd:
            command_msg = parse_command(user_cmd)
            if command_msg:
                send_command_to_env(state, command_msg)
            if user_cmd.strip().lower() == "stop":
                state.running = False

        # 3. Rafraîchit l'affichage si nécessaire


        time.sleep(0.1)


def poll_env_messages(state: DisplayState) -> None:
    """
    Récupère tous les messages disponibles depuis `mq_from_env` sans bloquer,
    et traite chacun d'eux.

    Met à jour l'état interne (last_snapshot) lorsque des status sont reçus.
    """
    while True:
        try:
            msg = state.mq_from_env.get_nowait() #Non bloquant
            handle_env_message(state, msg)
        except Exception: # queue vide
            break  


def handle_env_message(state: DisplayState, msg: dict) -> None: #à revoir en fonction de besoins 
    """
    Traite les messages reçu depuis env.
    """

    pass



def read_user_command() -> Optional[str]:
    """
    Lit une commande utilisateur.

    Returns:
        La commande saisie (str) ou None si aucune entrée.
    """
    import select
    if select.select([sys.stdin], [], [], 0.0)[0]:
        return sys.stdin.readline().strip()     
    return None


def parse_command(cmd: str) -> Optional[dict]: #à revoir 
    """
    Analyse une commande textuelle et ce qu'il doit faire en fonction de cette commande.

    """
    pass 

def send_command_to_env(state: DisplayState, command_msg: dict) -> None:
    """
    Envoie une commande à env via `mq_to_env`.

    Args:
        command_msg: Dictionnaire représentant la commande (ex: {"cmd": "SET", ...}).
    """
    state.mq_to_env.put(command_msg)


def request_stop(state: DisplayState) -> None:
    """
    Déclenche l'arrêt côté display : envoie STOP à env et quitte la boucle UI.
    """
    send_command_to_env(state, {"cmd": "STOP"})
    state.running = False


def cleanup(state: DisplayState) -> None:
    """
    Libère proprement les ressources utilisées par le display.

    (Avec un manager, on se contente généralement de quitter proprement.
    Les queues/manager seront arrêtés côté env.)
    """
    print("[Display] Exiting cleanly...")


if __name__ == "__main__":
    display_main()
