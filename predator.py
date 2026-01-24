import os
import time
import socket
import json
from multiprocessing.managers import BaseManager

# Constantes globales 
ENV_HOST = 'localhost'
ENV_PORT = 1789

MANAGER_HOST = 'localhost'
MANAGER_PORT = 50000
AUTHKEY = b"llave"

TICK_SLEEP_DEFAULT = 0.2  # secondes
INITIAL_ENERGY = 100.0
ENERGY_GAIN_FROM_PREY = 20.0
REPRODUCTION_COST = 10.0

# Manager client
class EnvManager(BaseManager):
    pass

EnvManager.register("get_state")
EnvManager.register("get_sem_mutex")
EnvManager.register("get_sem_prey")


# Socket helpers

def send_json(sock: socket.socket, message: Dict[str, Any]) -> None:
    """
    Envoie un message JSON délimité par '\\n' (NDJSON).
    """
    data = (json.dumps(message) + "\n").encode("utf-8")
    sock.sendall(data)

# Point d'entrée
def predator_main() -> None:
    """
    Point d'entrée du processus prédateur.
    Initialise les mécanismes de communication inter-processus, rejoint la simultaion et exécute la boucle proincipale du prédateur.
    """
    state = init_ipc()
    join_simulation(state)
    simulation_loop(state)
    cleanup(state)

# Initialisation IPC
def init_ipc() -> Dict[str, Any]:
    """
    Initialise et attache tous les mécanismes IPC nécessaires au prédateur.
    Cette fonction ouvre la mémoire partagée, les sémaphores requis et établit la connexion socket avec le processus environnement.
    """
    pid = os.getpid()

    # Connexion au manager (env héberge l'état global)
    mgr = EnvManager(address=(MANAGER_HOST, MANAGER_PORT), authkey=AUTHKEY)
    mgr.connect()

    shared_state = mgr.get_state()
    sem_mutex = mgr.get_sem_mutex()
    sem_prey = mgr.get_sem_prey()  

    # Socket vers env (uniquement pour JOIN)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ENV_HOST, ENV_PORT))

    return {
        "state": shared_state,
        "sem_mutex": sem_mutex,
        "sem_prey": sem_prey,
        "socket": sock,
        "pid": pid,
        "energy": INITIAL_ENERGY,
        "active": True
    }

# Join (socket)

def join_simulation(state: Dict[str, Any]) -> None:
    """
    Signale à env l'arrivée d'un prédateur (socket)
    """
    send_json(state["socket"], {"role": "predator", "pid": state["pid"]})
    # à voir si c'est env qui modifie la mémoire partagée ou le prédateur


# Lecture de paramètres globaux
def read_global_parameters(state: PredatorState) -> Dict[str, Any]:
    state.sem_mutex.acquire()
    
    state.sem_mutex.release()

    return {
        "running": ,
        "H_pred": ,
        "R_pred": ,
        "energy_decay": ,
    }

# Boucle de simulation
def simulation_loop(state: PredatorState) -> None:
    """
    Boucle principale de la simulation du prédateur.
    À chaque itération, le prédateur met à jour son énergie et son état, tente de chasser, se reproduit ou meurt, puis attend le prochain tick de simulation.
    """
    while True:
        params = read_global_parameters(state)

        if not params["running"]:
            break

        update_energy(state, params["energy_decay"])
        update_activity_state(state, params["H_pred"])

        if state.active:
            hunted = try_hunt(state)
            if hunted:
                consume_prey(state)

        if can_reproduce(state, params["R_pred"]):
            reproduce(state)

        if is_dead(state):
            notify_death(state)
            break

        sleep_tick()


# Gestion de l'énergie et de l'état
def update_energy(state: PredatorState, energy_decay: float) -> None:
    """
    Met à jour l'énergie du prédateur en appliquant la perte d'énergie liée à l'écoulement du temps.
    """
    state.energy -= energy_decay


def update_activity_state(state: PredatorState, activation_threshold: float) -> None:
    """
    Met à jour l'état actif ou passif du prédateur en fonction de son énergie et du seuil d'activation global.
    """
    state.active = state.energy < activation_threshold


# Chasse (alimentation)
def hunt(state: PredatorState) -> bool:
    """
    Tente de chasser une proie active.
    Cette fonction essaie d'acquérir le sémaphore représentant les proies actives disponibles.
    
    Retourne :
        True si une proie a pu être chassée,
        False sinon.
    """
    return state.sem_prey.acquire(blocking=False)


def consume_prey(state: PredatorState) -> None:
    """
    Traite la consommation d'une proie par le prédateur.
    Met à jour l'énergie du prédateur et notifie le processus environnement de l'événement.
    """
    state.energy += ENERGY_GAIN_FROM_PREY
    send_json(state.socket, {"type": "eat_prey", "pid": state.pid})


# Reproduction
def can_reproduce(state: PredatorState,reproduction_threshold: float) -> bool:
    """
    Détermine si le prédateur peut se reproduire.
    Le prédateur est reproductible si son énergie dépasse le seuil de reproduction global.
    
    Retourne :
        True si la reproduction est possible,
        False sinon.
    """
    return state.energy > reproduction_threshold


def reproduce(state: PredatorState) -> None:
    """
    Signale au processus environnement une demande de reproduction du prédateur, ce qui entraîne une augmentation de la population.
    """
    state.energy -= REPRODUCTION_COST
    send_json(state.socket, {"type": "reproduce", "role": "predator", "pid": state.pid})


# Mort et arrêt
def is_dead(state: PredatorState) -> bool:
    """
    Vérifie si le prédateur est mort.
    Le prédateur est considéré comme mort lorsque son énergie devient négative.
    
    Retourne :
        True si le prédateur est mort,
        False sinon.
    """
    return state.energy < 0


def notify_death(state: PredatorState) -> None:
    """
    Informe le processus environnement de la mort du prédateur afin que la population globale soit mise à jour.
    """
    send_json(state.socket, {"type": "death", "role": "predator", "pid": state.pid})
    # à vérifier comment on fait

# Utilitaires
def sleep_tick() -> None:
    time.sleep(TICK_SLEEP_DEFAULT)

def cleanup(state: PredatorState) -> None:
    """
    Libère proprement les ressources utilisées par le prédateur.
    Ferme la connexion socket et détache les mécanismes IPC locaux avant la terminaison du processus.
    """
    pass

# Lancememt

if __name__ == "__main__":
    predator_main()