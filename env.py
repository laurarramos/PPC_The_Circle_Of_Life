import os
import random
import threading
import socket
import signal
import time
from multiprocessing import Semaphore, Queue
from multiprocessing.managers import BaseManager


HOST = "localhost"
PORT = 1789
MANAGER_PORT = 50000
AUTHKEY = b"llave"

class SharedState:
    """
    Structure de données partagées entre les processus via mémoire partagée.
    """
    def __init__(self, grass, nb_preys, pid_preys_active, nb_predators, H, R, drought=False, energy_decay=1):
        self.grass = grass
        self.nb_preys = nb_preys
        self.pid_preys_active = pid_preys_active
        self.nb_predators = nb_predators
        self.H = H
        self.R = R
        self.drought = drought
        self.energy_decay = energy_decay
    

class EnvManager(BaseManager):
    pass


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
        # Mémoire partagée
        self.shared_state = SharedState(grass=100, nb_preys=0, pid_preys=[], nb_predators=0, pid_predators=[], H=5, R=2)
        # Semaphores
        self.sem_mutex = Semaphore(1)
        self.sem_grass = Semaphore(self.shared_state.grass)
        self.sem_prey = Semaphore(0)

        # Socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((HOST, PORT))
        self.server_socket.listen()

        # Display communication
        self.d_to_env = Queue()
        self.env_to_d = Queue()

        #Manager



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

    def grass_growth(self):
        """
        Augmente la quantité d'herbe dans l'environnement.
        """
        #doit modifier sem_grass puis shared_state.grass
        pass

    def schedule_message_queue(self):
        """
        Envoie périodiquement l'état partagé vers le display via la file de messages.
        """
        pass 

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

    def client_message(self, client_socket):
        """
        Met à jour les états partagés en fonction des messages écoutés dans la socket.
        """
        with client_socket:
            data = client_socket.recv(1024).decode().strip()

            if data.get("role")=="prey":
                self.shared_state.nb_preys += 1
            if data.get("role")=="predator":
                self.shared_state.nb_predators += 1


    def cleanup(self):
        self.server_socket.close()
