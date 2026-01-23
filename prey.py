from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict

from multiprocessing.shared_memory import SharedMemory


# Config 
ENV_HOST = 'localhost'
ENV_PORT = 1789

TICK_SLEEP_DEFAULT = 0.2  
INITIAL_ENERGY = 100.0
ENERGY_GAIN_FROM_GRASS = 10.0
REPRODUCTION_COST = 5.0


class PreyState:
    """
    Représente l'état interne d'une proie.

    Cette classe regroupe :
    - l'état de l'individu (énergie, actif/passif),
    - les références vers les mécanismes IPC (mémoire partagée, sémaphores, socket) nécessaires pour interagir avec le processus environnement.
    """

    def __init__(self, pid: int, shm: SharedState, sem_mutex: Any, sem_grass: Any, sem_prey: Any, socket: socket.socket, energy: float = INITIAL_ENERGY, active: bool = True) -> None:
        """
        Initialise l'état d'une proie.

        Args:
            pid: Identifiant du processus proie.
            shm: Référence vers la mémoire partagée.
            sem_mutex: Sémaphore binaire protégeant l'accès à la mémoire partagée.
            sem_grass: Sémaphore (compteur) modélisant la quantité d'herbe disponible.
            sem_prey: Sémaphore (compteur) modélisant le nombre de proies actives chassables.
            socket: Socket de communication avec le processus environnement.
            energy: Énergie initiale de la proie.
            active: État initial (actif/passif).
            has_prey_token: Indicateur si cette proie a déposé 1 jeton dans sem_prey = s'il y a une nouvelle proie active et chassable.
        """
        self.pid = pid
        self.energy = energy
        self.active = active

        # Indique si la proie a déposé un jeton dans sem_prey (proie active chassable).
        # Permet de garder la cohérence lors des transitions d'état ou de la mort.
        self.has_prey_token = False

        # IPC handles
        self.shm = shm
        self.sem_mutex = sem_mutex
        self.sem_grass = sem_grass
        self.sem_prey = sem_prey
        self.socket = socket

# Outils socket
def send_json(sock: socket.socket, message: Dict[str, Any]) -> None:
    """
    Envoie un message JSON terminé par un saut de ligne.
    """
    data = (json.dumps(message) + "\n").encode("utf-8")
    sock.sendall(data)


# Point d'entrée
def prey_main() -> None:
    """
    Point d'entrée du processus proie.

    Initialise les mécanismes de communication inter-processus, rejoint la simulation et exécute la boucle principale de la proie.
    """
    state = init_ipc()
    join_simulation(state)
    simulation_loop(state)
    cleanup(state)


# Initialisation IPC
def init_ipc() -> PreyState:
    """
    Initialise et attache tous les mécanismes IPC nécessaires à la proie.

    Cette fonction :
    - attache la mémoire partagée,
    - ouvre les sémaphores requis,
    - établit la connexion socket avec le processus environnement,
    - construit et retourne l'objet PreyState.
    """
    pid = os.getpid()

    # Mémoire partagée (crée par env)
    shm = attach_shared_memory()

    # Manager IPC (démarré par env)
    mgr = connect_ipc_manager()
    sem_mutex, sem_grass, sem_prey, q_to_env, q_from_env = get_ipc_handles_from_manager(mgr)
    # prey n'utilise que sem_mutex, sem_grass et sem_prey
    _ = q_to_env, q_from_env

    # Socket vers env
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ENV_HOST, ENV_PORT))

    return PreyState(pid=pid, shm=shm, sem_mutex=sem_mutex, sem_grass=sem_grass, sem_prey=sem_prey, socket=sock, energy=INITIAL_ENERGY, active=True, has_prey_token=False)


# Enregistrement
def join_simulation(state: PreyState) -> None:
    """
    Signale au processus environnement l'arrivée d'une nouvelle proie.

    Envoie un message de type JOIN (au minimum : rôle + pid).
    """
    send_json(state.socket, {"type": "join", "role": "prey", "pid": state.pid})


# Lecture paramètres globaux
def read_global_parameters(state: PreyState) -> Dict[str, Any]:
    state.sem_mutex.acquire()
    snap: SharedStateSnapshot = read_snapshot(state.shm)
    state.sem_mutex.release()

    return {
        "running": snap.running,
        "H_prey": snap.H_prey,
        "R_prey": snap.R_prey,
        "energy_decay": snap.energy_decay,
    }


# Boucle principale
def simulation_loop(state: PreyState) -> None:
    """
    Boucle principale de la simulation de la proie.

    À chaque itération, la proie :
    - met à jour son énergie,
    - met à jour son état actif/passif (et sa "chassabilité"),
    - tente de manger de l'herbe si elle est active,
    - se reproduit si possible,
    - meurt si son énergie devient négative, puis attend le prochain tick de simulation.

    Remarque :
        Seules les proies actives peuvent être prédatées (modélisé via sem_prey).
    """
    while True:
        params = read_global_parameters(state)

        if not params["running"]:
            break

        update_energy(state, params["energy_decay"])
        update_activity_state(state, params["H_prey"])

        if state.active:
            deposit_prey_token_if_needed(state)
            ate = try_eat_grass(state)
            if ate:
                consume_grass(state)
        else:
            withdraw_prey_token_if_needed(state)


        if can_reproduce(state, params["R_prey"]):
            reproduce(state)

        if is_dead(state):
            notify_death(state)
            break

        sleep_tick()

# Logique de la proie
def update_energy(state: PreyState, energy_decay: float) -> None:
    """
    Met à jour l'énergie de la proie en appliquant la perte d'énergie liée à l'écoulement du temps (décroissance par tick).
    """
    state.energy -= energy_decay


def update_activity_state(state: PreyState, activation_threshold: float) -> None:
    """
    Met à jour l'état actif/passif de la proie en fonction de son énergie et du seuil d'activation global.

    Cette fonction gère également la cohérence du sémaphore `sem_prey` :
    - si la proie devient active, elle "dépose" un jeton (release),
    - si elle redevient passive, elle "retire" son jeton (acquire), afin de refléter le nombre de proies actives chassables.

    Args:
        activation_threshold: Seuil H au-dessous duquel l'individu devient actif.
    """
    state.active = state.energy < activation_threshold


def deposit_prey_token_if_needed(state: PreyState) -> None:
    """
    Si la proie devient active et n'a pas encore déposé de jeton, elle dépose 1 jeton dans sem_prey.
    """
    if not state.has_prey_token:
        state.sem_prey.release()
        state.has_prey_token = True


def withdraw_prey_token_if_needed(state: PreyState) -> None:
    """
    Si la proie devient passive et avait déposé un jeton, elle le retire de sem_prey.
    """
    if state.has_prey_token:
        state.sem_prey.acquire(blocking=False)
        state.has_prey_token = False


def try_eat_grass(state: PreyState) -> bool:
    """
    Tente de consommer de l'herbe.

    Essaie d'acquérir `sem_grass` (portions d'herbe disponibles).
    Si l'acquisition réussit, l'énergie de la proie peut être augmentée.

    Returns:
        True si de l'herbe a pu être consommée, False sinon.
    """
    return state.sem_grass.acquire(blocking=False)


def consume_grass(state: PreyState) -> None:
    """
    Traite la consommation d'herbe par la proie.

    Met à jour l'énergie de la proie et, si le modèle le prévoit, notifie le processus environnement (par exemple pour maintenir un compteur d'herbe dans la mémoire partagée à des fins d'affichage).
    """
    state.energy += ENERGY_GAIN_FROM_GRASS
    send_json(state.socket, {"type": "eat_grass", "pid": state.pid})


def can_reproduce(state: PreyState, reproduction_threshold: float) -> bool:
    """
    Détermine si la proie peut se reproduire.

    La proie est reproductible si son énergie dépasse le seuil R.

    Args:
        reproduction_threshold: Seuil R de reproduction.

    Returns:
        True si la reproduction est possible, False sinon.
    """
    return state.energy > reproduction_threshold


def reproduce(state: PreyState) -> None:
    """
    Signale au processus environnement une demande de reproduction de la proie.

    L'environnement met à jour la population globale et applique, si besoin, une politique de création d'un nouvel individu (selon le design retenu).
    """
    state.energy -= REPRODUCTION_COST
    send_json(state.socket, {"type": "reproduce", "role": "prey", "pid": state.pid})


def is_dead(state: PreyState) -> bool:
    """
    Vérifie si la proie est morte.

    La proie est considérée comme morte lorsque son énergie devient négative.

    Returns:
        True si la proie est morte, False sinon.
    """
    return state.energy < 0


def notify_death(state: PreyState) -> None:
    """
    Informe le processus environnement de la mort de la proie afin que la population globale soit mise à jour (décrément du compteur global).
    """
    withdraw_prey_token_if_needed(state)
    send_json(state.socket, {"type": "death", "role": "prey", "pid": state.pid})
    # à modifier : c'est predateur qui modifie direct dans la mémoire partagée qu il a tué une proie

# Utilitaires

def cleanup(state: PreyState) -> None:
    """
    Libère proprement les ressources utilisées par la proie.

    Ferme la connexion socket et détache/ferme les ressources IPC locales avant la terminaison du processus.

    Remarque :
        Si la proie meurt alors qu'elle est active, elle doit d'abord retirer son jeton de `sem_prey` pour rester cohérente.
    """
    state.socket.close()
    state.shm.close()



def sleep_tick() -> None:
    """
    Suspend l'exécution de la proie pendant une durée donnée afin de simuler l'écoulement du temps entre deux itérations de la simulation.

    Args:
        base_delay: Durée de base (en secondes) du tick.
    """
    time.sleep(TICK_SLEEP_DEFAULT)

# Lancement
if __name__ == "__main__":
    prey_main()