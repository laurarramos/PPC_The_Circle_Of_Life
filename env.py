import os
import random
import threading
import socket
import signal
import time
import json
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
    def __init__(self, grass, nb_preys, pid_preys_active, nb_predators, H, R, drought=False, energy_decay=1, serve=True):
        self.grass = grass
        self.nb_preys = nb_preys
        self.pid_preys_active = pid_preys_active
        self.nb_predators = nb_predators
        self.H = H
        self.R = R
        self.drought = drought
        self.energy_decay = energy_decay
        self.serve = serve
    

class EnvManager(BaseManager):
    pass

EnvManager.register("get_state")
EnvManager.register("get_sem_grass")
EnvManager.register("get_sem_mutex")
EnvManager.register("get_d_to_env")
EnvManager.register("get_env_to_d")

class EnvProcess:
    """
    Représente l'état global de l'environnement (populations, herbe, sécheresse,...).
    
    - reçoit des commandes utilisateur du display via une file de message
    - ouvre un serveur socket auqelle les populations se connectent pour interagir avec l'environnement lors d'événements (manger, naissances, morts)
    - maintient l'état partagé dans une mémoire partagée
    - gère les sémaphores pour la synchronisation des accès aux ressources partagées 
    """
    def __init__(self):


        # Manager
        self.manager = EnvManager(address=(HOST, MANAGER_PORT), authkey=AUTHKEY)


        EnvManager.register("get_state", callable=lambda: self.shared_state)
        EnvManager.register("get_sem_grass", callable=lambda: self.sem_grass)
        EnvManager.register("get_sem_mutex", callable=lambda: self.sem_mutex)
        EnvManager.register("get_d_to_env", callable=lambda: self.d_to_env)
        EnvManager.register("get_env_to_d", callable=lambda: self.env_to_d)

        # Mémoire partagée
        self.shared_state = SharedState(grass=100, nb_preys=0, pid_preys_active=[], nb_predators=0, H=5, R=2, drought=False, energy_decay=1, serve=True)
       
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


    def start(self):
        signal.signal(signal.SIGUSR1, self.drought_handler)

        try:
            self.manager.start()
            print("[EnvProcess] Manager démarré.")
        except Exception as e:
            print(f"[EnvProcess] Erreur lors du démarrage du manager: {e}")
            self.shared_state.serve = False
            return
        
        threading.Thread(target=self.handle_connections, daemon=True).start()

        threading.Thread(target=self.process_display_command, daemon=True).start()

        self.schedule_random_drought()
        self.schedule_message_queue()

        while self.shared_state.serve:
            time.sleep(1)

        self.cleanup()

    def grass_growth(self):
        """
        Augmente la quantité d'herbe dans l'environnement.
        """
        #doit modifier sem_grass puis shared_state.grass
        pass

    def process_display_command(self):
        """
        Traite les commandes reçues depuis le display via la file de messages d_to_env.
        """
        while self.shared_state.serve:  # Utilise shared_state.serve
            try:
                command_msg = self.d_to_env.get(timeout=0.1)
                if command_msg.get("cmd") == "SET_GRASS":
                    with self.sem_mutex:
                        self.shared_state.grass = command_msg["value"]
                        self.sem_grass = Semaphore(self.shared_state.grass)
                elif command_msg.get("cmd") == "SET_PREYS":
                    with self.sem_mutex:
                        self.shared_state.nb_preys = command_msg["value"]
                elif command_msg.get("cmd") == "SET_PREDATORS":
                    with self.sem_mutex:
                        self.shared_state.nb_predators = command_msg["value"]
                elif command_msg.get("cmd") == "STOP":
                    self.shared_state.serve = False  # Met à jour shared_state.serve
            except Exception:
                continue

    def schedule_message_queue(self):
        """
        Envoie périodiquement l'état partagé vers le display via la file de messages.
        """
        def send_state_to_display():
            while self.shared_state.serve:
                with self.sem_mutex:
                    state = {
                        "grass": self.shared_state.grass,
                        "nb_preys": self.shared_state.nb_preys,
                        "nb_predators": self.shared_state.nb_predators,
                        "drought": self.shared_state.drought,
                        "H": self.shared_state.H,
                        "R": self.shared_state.R,
                    }
                    self.env_to_d.put(state)
                time.sleep(1)  
        threading.Thread(target=send_state_to_display, daemon=True).start()   


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
        if self.shared_state.serve:
            os.kill(os.getpid(), signal.SIGUSR1)

    def drought_handler(self, signum, frame):
        with self.sem_mutex:
            old = self.shared_state.grass
            new = old // 2
            delta = old - new

            #Met à jour l'état partagé
            self.shared_state.grass = new
            self.shared_state.drought = True
            print(f"[EnvProcess] Drought occurred! Grass reduced from {old} to {new}.")

        #Retire physiquement l’herbe
        for _ in range(delta):
            self.sem_grass.acquire()

        #Planifie une nouvelle sécheresse alétaoire 
        self.schedule_random_drought()


    def handle_connections(self):
        while self.shared_state.serve:
            try:
                client, addr = self.server_socket.accept()
                threading.Thread(
                    target=self.client_message,
                    args=(client,),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[EnvProcess] Erreur dans handle_connections: {e}")
                time.sleep(1)  

    def client_message(self, client_socket):
        """
        Met à jour les états partagés en fonction des messages écoutés dans la socket.
        """
        with client_socket:
            data = client_socket.recv(1024).decode().strip()
            try: 
                message = json.loads(data)
                if message.get("role")=="prey":
                    with self.sem_mutex:
                        self.shared_state.nb_preys += 1
                if message.get("role")=="predator":
                    with self.sem_mutex:
                        self.shared_state.nb_predators += 1
            except json.JSONDecodeError:
                print(f"[EnvProcess] Message JSON invalide reçu: {data}")
            except Exception as e:
                print(f"[EnvProcess] Erreur inattendue {e}")

    def cleanup(self):
        self.manager.shutdown()
        self.server_socket.close()
