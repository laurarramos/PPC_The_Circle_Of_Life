from __future__ import annotations

import struct
from dataclasses import dataclass
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.managers import SyncManager
from typing import Optional, Tuple


# Names / network constants

SHM_NAME = "eco_shm"

MANAGER_HOST = "127.0.0.1"
MANAGER_PORT = 50051
MANAGER_AUTHKEY = b"eco_authkey"  # à mettre aussi en variable d'env si vous voulez


# Shared memory layout

# On stocke un "snapshot" binaire simple, stable et rapide.
#
# Format struct (little-endian):
#   running:        ?   (bool)
#   drought:        ?   (bool)
#   padding:        2x  (2 bytes padding)
#   nb_preys:       i   (int32)
#   nb_predators:   i   (int32)
#   grass_count:    i   (int32)  # pour affichage; la ressource "mangeable" est sem_grass
#   H_prey:         f   (float32)
#   H_pred:         f   (float32)
#   R_prey:         f   (float32)
#   R_pred:         f   (float32)
#   energy_decay:   f   (float32)
#   grass_growth:   f   (float32)
#
_STATE_STRUCT = struct.Struct("<??2xiii ffffff")
STATE_SIZE = _STATE_STRUCT.size


@dataclass
class SharedStateSnapshot:
    """Représentation Python de l'état global (pour lecture/écriture)."""
    running: bool
    drought: bool
    nb_preys: int
    nb_predators: int
    grass_count: int
    H_prey: float
    H_pred: float
    R_prey: float
    R_pred: float
    energy_decay: float
    grass_growth: float


def default_snapshot() -> SharedStateSnapshot:
    """Valeurs par défaut au lancement de env."""
    return SharedStateSnapshot(
        running=True,
        drought=False,
        nb_preys=0,
        nb_predators=0,
        grass_count=1000,
        H_prey=50.0,
        H_pred=50.0,
        R_prey=10.0,
        R_pred=10.0,
        energy_decay=1.0,
        grass_growth=5.0,
    )


# Shared memory helpers

def create_shared_memory(initial: Optional[SharedStateSnapshot] = None) -> SharedMemory:
    """
    Crée la shared memory nommée et écrit l'état initial.
    À appeler UNIQUEMENT dans env.py.
    """
    shm = SharedMemory(name=SHM_NAME, create=True, size=STATE_SIZE)
    snap = initial if initial is not None else default_snapshot()
    write_snapshot(shm, snap)
    return shm


def attach_shared_memory() -> SharedMemory:
    """S'attache à la shared memory existante. À appeler dans prey.py / predator.py / display.py si besoin."""
    return SharedMemory(name=SHM_NAME, create=False)


def read_snapshot(shm: SharedMemory) -> SharedStateSnapshot:
    """Lit l'état global depuis la shared memory (sans synchronisation : protéger par sem_mutex côté appelant)."""
    data = bytes(shm.buf[:STATE_SIZE])
    unpacked = _STATE_STRUCT.unpack(data)
    return SharedStateSnapshot(
        running=unpacked[0],
        drought=unpacked[1],
        nb_preys=unpacked[2],
        nb_predators=unpacked[3],
        grass_count=unpacked[4],
        H_prey=unpacked[5],
        H_pred=unpacked[6],
        R_prey=unpacked[7],
        R_pred=unpacked[8],
        energy_decay=unpacked[9],
        grass_growth=unpacked[10],
    )


def write_snapshot(shm: SharedMemory, snap: SharedStateSnapshot) -> None:
    """Écrit l'état global dans la shared memory (protéger par sem_mutex côté appelant)."""
    packed = _STATE_STRUCT.pack(
        bool(snap.running),
        bool(snap.drought),
        int(snap.nb_preys),
        int(snap.nb_predators),
        int(snap.grass_count),
        float(snap.H_prey),
        float(snap.H_pred),
        float(snap.R_prey),
        float(snap.R_pred),
        float(snap.energy_decay),
        float(snap.grass_growth),
    )
    shm.buf[:STATE_SIZE] = packed


# Manager for semaphores/queues (processes launched separately)

class IPCManager(SyncManager):
    """Manager réseau qui héberge sem_mutex, sem_grass, sem_prey et les queues pour display/env."""
    pass


# Ces registres seront complétés par env au moment du lancement
IPCManager.register("get_sem_mutex")
IPCManager.register("get_sem_grass")
IPCManager.register("get_sem_prey")
IPCManager.register("get_queue_to_env")
IPCManager.register("get_queue_from_env")


def start_ipc_manager(
    sem_mutex,
    sem_grass,
    sem_prey,
    queue_to_env,
    queue_from_env,
) -> IPCManager:
    """
    Démarre le manager serveur (à appeler dans env.py).
    Les autres processus se connecteront via connect_ipc_manager().
    """
    def _get_sem_mutex():
        return sem_mutex

    def _get_sem_grass():
        return sem_grass

    def _get_sem_prey():
        return sem_prey

    def _get_queue_to_env():
        return queue_to_env

    def _get_queue_from_env():
        return queue_from_env

    # On re-register avec callables (uniquement côté serveur)
    IPCManager.register("get_sem_mutex", callable=_get_sem_mutex)
    IPCManager.register("get_sem_grass", callable=_get_sem_grass)
    IPCManager.register("get_sem_prey", callable=_get_sem_prey)
    IPCManager.register("get_queue_to_env", callable=_get_queue_to_env)
    IPCManager.register("get_queue_from_env", callable=_get_queue_from_env)

    mgr = IPCManager(address=(MANAGER_HOST, MANAGER_PORT), authkey=MANAGER_AUTHKEY)
    mgr.start()
    return mgr


def connect_ipc_manager() -> IPCManager:
    """
    Se connecte au manager serveur (à appeler dans prey.py / predator.py / display.py).
    """
    mgr = IPCManager(address=(MANAGER_HOST, MANAGER_PORT), authkey=MANAGER_AUTHKEY)
    mgr.connect()
    return mgr


def get_ipc_handles_from_manager(mgr: IPCManager) -> Tuple[object, object, object, object, object]:
    """
    Récupère les proxys vers :
    sem_mutex, sem_grass, sem_prey, queue_to_env, queue_from_env
    """
    sem_mutex = mgr.get_sem_mutex()
    sem_grass = mgr.get_sem_grass()
    sem_prey = mgr.get_sem_prey()
    q_to_env = mgr.get_queue_to_env()
    q_from_env = mgr.get_queue_from_env()
    return sem_mutex, sem_grass, sem_prey, q_to_env, q_from_env
