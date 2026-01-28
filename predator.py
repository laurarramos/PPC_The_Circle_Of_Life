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

TICK_SLEEP_DEFAULT = 1.5
INITIAL_ENERGY = 100.0
ENERGY_GAIN_FROM_PREY = 20.0
REPRODUCTION_COST = 30.0

# Manager client
class EnvManager(BaseManager):
    pass

EnvManager.register("get_state")
EnvManager.register("get_sem_mutex")
EnvManager.register("get_sem_prey")

# Utilitaires
def send_json(sock: socket.socket, message: dict) -> None:
    """
    Envoie un message JSON terminé par un saut de ligne.
    """
    data = (json.dumps(message) + "\n").encode("utf-8")
    sock.sendall(data)
    print(f"[Socket] Sent: {message}")

def init_ipc() -> dict:
    """
    Initialise les connexions au manager et à la socket.
    """
    print("[Init] Connecting to manager...")
    mgr = EnvManager(address=(MANAGER_HOST, MANAGER_PORT), authkey=AUTHKEY)
    mgr.connect()
    print("[Init] Manager connected ✓")

    print("[Init] Connecting to environment socket...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ENV_HOST, ENV_PORT))
    print("[Init] Socket connected ✓")

    return {
        "pid": os.getpid(),
        "shared_state": mgr.get_state(),
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
        print(f"[Predator {state['pid']}] Trying to hunt...")

        sucess = False # variable pour savoir si on a effectivement trouvé un PID

        state["sem_mutex"].acquire()
        pids = state["shared_state"].get("pid_preys_active", [])
        
        if pids:
            # On retire la première proie de la liste (consommation)
            victim_pid = pids.pop(0)
            state["shared_state"].update({"pid_preys_active": pids})
            
            # Mise à jour de l'énergie locale et du compteur global
            state["energy"] += ENERGY_GAIN_FROM_PREY
            
            # On décrémente le nombre total de proies dans l'environnement
            nb = state["shared_state"].get("nb_preys", 0)
            state["shared_state"].update({"nb_preys": max(0, nb - 1)})
            
            print(f"[Predator {state['pid']}] Ate prey {victim_pid}, energy now: {state['energy']:.1f}")
            sucess = True
        
        else:
            print(f"[Predator {state['pid']}] No prey available")

        state["sem_mutex"].release()
        if not sucess:
            state["sem_prey"].release()
    else:
        print(f"[Predator {state['pid']}] Prey semaphore unavailable (hunting in progress elsewhere)")

def try_reproduce(state) -> bool:
    """
    Logique de reproduction sexuée via la mémoire partagée.
    Gère le rdv entre deux prédateurs prêts à se reproduire et la perte d'énergie.
    """
    state["sem_mutex"].acquire()
    try :
        partner_pid = state["shared_state"].get("waiting_predator_pid")

        if partner_pid is None:
            # Cas 1 : Je suis le premier. Je perd de l'énergie et je m'inscris.
            state["energy"] -= REPRODUCTION_COST
            state["shared_state"].update({"waiting_predator_pid": state["pid"]})
            print(f"[Predator {state['pid']}] Premier parent : Energie déduite, en attente...")
            return False

        elif partner_pid != state["pid"]:
            # Cas 2 : Je trouve quelqu'un. Je paie et je déclenche la naissance.
            state["shared_state"].update({"waiting_predator_pid": None})
            state["energy"] -= REPRODUCTION_COST
            send_json(state["socket"], {"type": "reproduce", "role": "predator", "pid": state["pid"]})
            print(f"[Predator {state['pid']}] Second parent : Energie déduite, bébé né avec {partner_pid} !")
            return True
        
        else:
                # On est tombé sur soi-même, on attend
                return False
    finally:
        # On libère le mutex dans tous les cas
        state["sem_mutex"].release()

def main_loop(state) -> None:
    """
    Boucle de simulation principale du prédateur
    """
    alive = True
    tick = 0

    while alive:
        tick += 1
        params = state["shared_state"]

        # 1. Vérification si la simulation doit s'arrêter (demandé par display)
        if not params.get("serve", True):
            print(f"[Predator {state['pid']}] Global stop received.")
            alive = False
            continue

        # 2. Récupération des seuils depuis la mémoire partagée
        h_threshold = params.get("H")
        r_threshold = params.get("R")
        energy_decay = params.get("energy_decay")

        # 3. Métabolisme : diminution régulière de l'énergie
        state["energy"] -= energy_decay
        print(f"[Predator {state['pid']}] Tick {tick}: Energy = {state['energy']:.1f} (decay: {energy_decay})")

        # 4. Chasse (énergie < H)
        if state["energy"] < h_threshold:
            print(f"[Predator {state['pid']}] Hungry! (energy < {h_threshold})")
            try_hunt(state)

        # 5. Reproduction (énergie > R)
        if alive and state["energy"] > r_threshold:
            print(f"[Predator {state['pid']}] Ready to reproduce!")
            try_reproduce(state)

        # 6. Condition de mort naturelle
        if state["energy"] <= 0:
            print(f"[Predator {state['pid']}] Died of hunger")
            alive = False
        
        time.sleep(TICK_SLEEP_DEFAULT)

def cleanup(state) -> None:
    """
    Libère les ressources en mettant à jour la mémoire partagée.
    Gère le retrait du compteur et de la liste d'attente de reproduction.
    """
    print(f"[Predator {state['pid']}] Cleanup: removing myself from shared state")
    
    # Utilisation de try...finally pour garantir la libération du mutex
    state["sem_mutex"].acquire()
    try:
        # 1. Mise à jour du compteur global de prédateurs
        current_nb = state["shared_state"].get("nb_predators", 0)
        state["shared_state"].update({"nb_predators": max(0, current_nb - 1)})

        # 2. NETTOYAGE REPRODUCTION : Retrait de la liste d'attente si nécessaire
        # Si je meurs alors que j'attendais un partenaire (mon PID est dans la liste d'attente)
        if state["shared_state"].get("waiting_predator_pid") == state["pid"]:
            state["shared_state"].update({"waiting_predator_pid": None})
            print(f"[Predator {state['pid']}] Cleared from waiting list (energy was already spent).")
            
    except Exception as e:
        print(f"[Predator {state['pid']}] Error during cleanup: {e}")
        
    finally:
        # Libération systématique du mutex pour éviter les deadlocks
        state["sem_mutex"].release()

    # 3. Fermeture de la socket de communication
    state["socket"].close()
    


# Lancement
if __name__ == "__main__":
    print("[Main] Starting predator process...")
    ipc = init_ipc()
    # État local du prédateur
    state = {**ipc, "energy": INITIAL_ENERGY}
    
    # Signalement de l'arrivée au processus env
    print(f"[Main] Predator PID: {state['pid']}, Initial energy: {state['energy']}")
    send_json(state["socket"], {"type": "join", "role": "predator", "pid": state["pid"]})
    
    main_loop(state)
    cleanup(state)
    print("[Main] Predator process ended")