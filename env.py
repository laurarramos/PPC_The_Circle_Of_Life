import os
import random
import threading
import socket
import signal
import time
from multiprocessing import Semaphore, Queue
from multiprocessing.shared_memory import SharedMemory

from shared_state import (
    create_shared_memory,
    read_snapshot,
    write_snapshot,
)

HOST = "localhost"
PORT = 1789


class EnvProcess:
    """
    Représente l'état global de l'environnement (populations, herbe, sécheresse,...).
    
    - reçoit des commandes utilisateur du display via une file de message
    - ouvre un serveur socket auqelle les populations se connectent pour interagir avec l'environnement lors d'événements (manger, naissances, morts)
    - maintient l'état partagé dans une mémoire partagée
    - gère les sémaphores pour la synchronisation des accès aux ressources partagées 
    """
    def __init__(self):
        self.serve = True

        # Shared memory --> changer pour utiliser un Manager  
        self.shm = create_shared_memory()
        self.shared_state = read_snapshot(self.shm)

        # Semaphores
        self.sem_mutex = Semaphore(1)
        self.sem_grass = Semaphore(self.shared_state.grass)
        self.sem_prey = Semaphore(0)
        self.sem_predator = Semaphore(0)

        # Socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen()

        # Display communication
        self.message_queue = Queue()


    def start(self):
        signal.signal(signal.SIGUSR1, self.drought_handler)

        threading.Thread(
            target=self.handle_connections,
            daemon=True
        ).start()

        self.schedule_random_drought()

        while self.serve:
            time.sleep(1)

        self.cleanup()

 
    def schedule_random_drought(self):
        """
        Planifie un délai aléatoire entre 15 et 60 secondes, puis envoie un signal pour déclencher une sécheresse quand ce délai est écoulé.
        """
        delay = random.randint(15, 60)
        threading.Timer(delay, self.trigger_drought).start()

    def trigger_drought(self):
        """
        Déclenche une sécheresse en envoyant un signal SIGUSR1.
    
        """
        if self.serve:
            os.kill(os.getpid(), signal.SIGUSR1)

    def drought_handler(self, signum, frame):
        with self.sem_mutex:
            old = self.shared_state.grass
            new = old // 2
            delta = old - new

            self.shared_state.grass = new
            self.shared_state.drought = True
            write_snapshot(self.shm, self.shared_state)

        # retirer physiquement l’herbe
        for _ in range(delta):
            self.sem_grass.acquire()

        self.schedule_random_drought()


    def handle_connections(self):
        while self.serve:
            client, addr = self.server_socket.accept()
            threading.Thread(
                target=self.process_client_message,
                args=(client,),
                daemon=True
            ).start()

    def process_client_message(self, client_socket):
        with client_socket:
            data = client_socket.recv(1024).decode().strip()

            if data == "stop":
                self.serve = False

            elif data == "eat_grass":
                self.handle_prey_eat()

            elif data == "eat_prey":
                self.handle_predator_eat()

            elif data == "prey_birth":
                self.update_preys(+1)

            elif data == "prey_death":
                self.update_preys(-1)

            elif data == "predator_birth":
                self.update_predators(+1)

            elif data == "predator_death":
                self.update_predators(-1)

    def handle_prey_eat(self):
        self.sem_grass.acquire()  # bloque s’il n’y a plus d’herbe

        with self.sem_mutex:
            self.shared_state.grass -= 1
            self.sem_prey.release()  # devient proie active
            write_snapshot(self.shm, self.shared_state)

    def handle_predator_eat(self):
        self.sem_prey.acquire()  # bloque s’il n’y a pas de proie active

        with self.sem_mutex:
            self.shared_state.nb_preys -= 1
            write_snapshot(self.shm, self.shared_state)

    def update_preys(self, delta):
        with self.sem_mutex:
            self.shared_state.nb_preys += delta
            write_snapshot(self.shm, self.shared_state)

    def update_predators(self, delta):
        with self.sem_mutex:
            self.shared_state.nb_predators += delta
            write_snapshot(self.shm, self.shared_state)


    def cleanup(self):
        self.server_socket.close()
