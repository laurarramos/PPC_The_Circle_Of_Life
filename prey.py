import os
import time
import socket
import json
from multiprocessing.managers import BaseManager

from pyparsing import Dict, Any

# Config globale
ENV_HOST = 'localhost'
ENV_PORT = 1789
MANAGER_HOST = 'localhost'
MANAGER_PORT = 50000
AUTHKEY = b"llave"

TICK_SLEEP_DEFAULT = 0.2  
INITIAL_ENERGY = 100.0
ENERGY_GAIN_FROM_GRASS = 10.0
REPRODUCTION_COST = 5.0

# Manager client
class EnvManager(BaseManager):
    pass

EnvManager.register("get_state")
EnvManager.register("get_sem_mutex")
EnvManager.register("get_sem_grass")
EnvManager.register("get_sem_prey")


# Utilitaires
def send_json(sock: socket.socket, message: Dict[str, Any]) -> None:
    """
    Envoie un message JSON terminé par un saut de ligne.
    """
    data = (json.dumps(message) + "\n").encode("utf-8")
    sock.sendall(data)

def init_ipc() -> dict:
    """
    Initialise les connexions au manager et à la socket
    """
    mgr = EnvManager(address=(MANAGER_HOST, MANAGER_PORT), authkey=AUTHKEY)
    mgr.connect()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ENV_HOST, ENV_PORT))

    return {
        "pid": os.getpid(),
        "shared_state": mgr.get_shared_state(),
        "sem_mutex": mgr.get_sem_mutex(),
        "sem_grass": mgr.get_sem_grass(),
        "sem_prey": mgr.get_sem_prey(),
        "socket": sock,
    }

# Logique fonctionnelle
def update_visibility(state, h_threshold: float) -> None:
    """
    Gère l'état actif/passif et l'inscription dans la liste chassable
    """
    is_hungry = state["energy"] < h_threshold

    if is_hungry and not state["active"]:
        # on vérouille manuellement l'accès à la mémoire partagée
        state["sem_mutex"].acquire()

        # on effectue la modification via le proxy
        pids = state["shared_state"].get("pid_preys_active", [])
        pids.append(state["pid"])
        state["shared_state"]["pid_preys_active"] = pids

        # on libère le mutex
        state["sem_mutex"].release()

        # on signale qu'une proie est active et chassable
        state["sem_prey"].release()
        state["active"] = True
    
    elif not is_hungry and state["active"]:
        withdraw_from_list(state)

def withdraw_from_list(state) -> None:
    """
    retire la proie de la liste des cibles sans arrêter le processus
    """
    if state["active"]:
        state["sem_mutex"].acquire()

        pids = state["shared_state"].get("pid_preys_active", [])
        if state["pid"] in pids:
            pids.remove(state["pid"])
            state["shared_state"]["pid_preys_active"] = pids

        state["sem_mutex"].release()

        state["sem_prey"].acquire(blocking=False)
        state["active"] = False

def check_if_eaten(state) -> bool:
    """
    vérifie dans la mémoire partagée si la proie a été mangée
    """
    eaten = False

    if state["active"]:
        state["sem_mutex"].acquire()
        pids = state["shared_state"].get("pid_preys_active", [])

        if state["pid"] not in pids:
            eaten = True
        
        state["sem_mutex"].release()
    return eaten

def main_loop(state) -> None:
    """
    Boucle de simulation principale de la proie 
    """
    alive = True

    while alive:
        params = state["shared_state"]

        # vérification si la simulation doit s'arrêter (demandé par display)
        if not params.get("serve", True):
            print(f"[Prey {state['pid']}] Global stop received.")
            alive = False
            continue

        # Récupération des seuils depuis la mémoire partagée
        h_threshold = params.get("H")
        r_threshold = params.get("R")
        energy_decay = params.get("energy_decay")

        state["energy"] -= energy_decay

        update_visibility(state, h_threshold)

        if state["active"]:
            if state["sem_grass"].acquire(blocking=False):
                state["energy"] += ENERGY_GAIN_FROM_GRASS
        
        if check_if_eaten(state):
            alive = False
            state["active"] = False
        
        if alive and state["energy"] > r_threshold:
            # demande de reproduction
            state["energy"] -= REPRODUCTION_COST
            send_json(state["socket"], {"type": "reproduce", "role": "prey", "pid": state["pid"]})

        if state["energy"] <= 0:
            alive = False
        
        time.sleep(TICK_SLEEP_DEFAULT)


def cleanup(state) -> None:
    """
    Libère les ressources et met à jour la mémoire partagée.
    """
    # on se retire de la liste des proies actives si besoin
    withdraw_from_list(state)

    # mise à jourdu compteur global de proies
    state["sem_mutex"].acquire()
    current_nb = state["shared_state"].get("nb_preys", 0)
    state["shared_state"]["nb_preys"] = max(0, current_nb - 1)
    state["sem_mutex"].release()

    # fermeture de la socket
    state["socket"].close()
    print(f"[Prey {state['pid']}] Cleanup done ✓")


# Lancement
if __name__ == "__main__":
    ipc = init_ipc()
    state = {**ipc, "energy": INITIAL_ENERGY, "active": False}
    send_json(state["socket"], {"type": "join", "role": "prey", "pid": state["pid"]})
    main_loop(state)
    cleanup(state)
    print("[Main] Prey process ended")