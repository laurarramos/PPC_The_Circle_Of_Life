import os
import time
import socket
import json
from multiprocessing.managers import BaseManager

from pyparsing import Any, Dict

# Constantes globales 
ENV_HOST = 'localhost'
ENV_PORT = 1789
MANAGER_HOST = 'localhost'
MANAGER_PORT = 50000
AUTHKEY = b"llave"

TICK_SLEEP_DEFAULT = 0.2
INITIAL_ENERGY = 100.0
ENERGY_GAIN_FROM_PREY = 20.0
REPRODUCTION_COST = 10.0

# Manager client
class EnvManager(BaseManager):
    pass

EnvManager.register("get_shared_state")
EnvManager.register("get_sem_mutex")
EnvManager.register("get_sem_prey")

# Utilitaires
def send_json(sock: socket.socket, message: dict) -> None:
    """
    Envoie un message JSON terminé par un saut de ligne.
    """
    data = (json.dumps(message) + "\n").encode("utf-8")
    sock.sendall(data)

def init_ipc() -> dict:
    """
    Initialise les connexions au manager et à la socket.
    """
    mgr = EnvManager(address=(MANAGER_HOST, MANAGER_PORT), authkey=AUTHKEY)
    mgr.connect()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ENV_HOST, ENV_PORT))

    return {
        "pid": os.getpid(),
        "shared_state": mgr.get_shared_state(),
        "sem_mutex": mgr.get_sem_mutex(),
        "sem_prey": mgr.get_sem_prey(),
        "socket": sock,
    }

# Logique fonctionnelle
def try_hunt(state) -> None:
    """
    Tente de chasser une proie si le sémaphore sem_prey est disponible
    """
    # On essaie d'acquérir un jeton de proie active (non bloquant)
    if state["sem_prey"].acquire(blocking=False):
        # On verrouille le mutex pour modifier la mémoire partagée
        state["sem_mutex"].acquire()
        
        pids = state["shared_state"].get("pid_preys_active", [])
        
        if pids:
            # On retire la première proie de la liste (consommation)
            victim_pid = pids.pop(0)
            state["shared_state"]["pid_preys_active"] = pids
            
            # Mise à jour de l'énergie locale et du compteur global
            state["energy"] += ENERGY_GAIN_FROM_PREY
            
            # On décrémente le nombre total de proies dans l'environnement
            nb = state["shared_state"].get("nb_preys", 0)
            state["shared_state"]["nb_preys"] = max(0, nb - 1)
            
            print(f"[Predator {state['pid']}] Ate prey {victim_pid}")
            
            # Libération du mutex après modification
            state["sem_mutex"].release()
        else:
            # Si la liste était vide par erreur de synchro, on libère le mutex
            state["sem_mutex"].release()
            # Et on rend le jeton sem_prey puisqu'on n'a pas mangé
            state["sem_prey"].release()

def main_loop(state) -> None:
    """
    Boucle de simulation principale du prédateur
    """
    alive = True

    while alive:
        params = state["shared_state"]
        h_threshold = params.get("H")
        r_threshold = params.get("R")
        energy_decay = params.get("energy_decay")

        # Diminution régulière de l'énergie
        state["energy"] -= energy_decay

        # Le prédateur tente de manger s'il a faim (énergie < H)
        if state["energy"] < h_threshold:
            try_hunt(state)

        # Gestion de la reproduction
        if alive and state["energy"] > r_threshold:
            state["energy"] -= REPRODUCTION_COST
            send_json(state["socket"], {"type": "reproduce", "role": "predator", "pid": state["pid"]})

        # Vérification de la mort
        if state["energy"] <= 0:
            print(f"[Predator {state['pid']}] Died of hunger")
            alive = False
        
        time.sleep(TICK_SLEEP_DEFAULT)

def cleanup(state) -> None:
    """
    Libère les ressources et informe de la mort.
    """
    send_json(state["socket"], {"type": "death", "role": "predator", "pid": state["pid"]})
    state["socket"].close()

# Lancement
if __name__ == "__main__":
    ipc = init_ipc()
    # État local du prédateur
    state = {**ipc, "energy": INITIAL_ENERGY}
    
    # Signalement de l'arrivée au processus env
    send_json(state["socket"], {"type": "join", "role": "predator", "pid": state["pid"]})
    
    main_loop(state)
    cleanup(state)