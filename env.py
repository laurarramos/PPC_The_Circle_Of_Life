import threading 
import socket
import signal
import time
import json

import multiprocessing import Semaphore, Queue
from multriprocessing.shared_memory import SharedMemory

from shared_state import (create_shared_memory, read_snapshot, write_snapshot, start_ipc_manager, SharedStateSnapshot)

#structure représntation population
class Population:

    def __init__(self, name, size, energy, is_active):
        self.name = name
        self.size = size
        self.energy = energy 
        self.is_active = is_active


#structure état global
class GlobalState:

    def __init__(self):
        self.nb_preys = 0
        self.nb_predators = 0
        self.grass = 1000  # Quantité initiale d'herbe
        self.H = 50  
        self.R = 10  
        self.drought = False  

#structure environnement 

class EnvProcess:
    def __init__(self):
        self.serve = True #Variable de contrôle boucle principale
        self.shared_state = SharedState() #état global partagé (données que les autres processus peuvent consulter et modifier)
        self.sem_mutex = Semaphore(1)
        self.sem_grass = Semaphore(self.shared_state.grass)  # Sémaphore nb herbe
        self.sem_prey = Semaphore(0)  # Sémaphore nb proies actives
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(('localhost', 1789))
        self.server_socket.listen(2) # listen(n) n=nb max de connexions en attente
        self.message_queue = Queue() #communication avec display process 


    def start (self):
        # Lance les threads pour gérer les connexions à la socket et les signaux 
        connection_thread = threading.Thread(target=self.handle_connections)
        signal_thread = threading.Thread(target=self.handle_signals)
        
        connection_thread.start()
        signal_thread.start()

        connection_thread.join()
        signal_thread.join()

        self.cleanup() #ferme les connexions et libère les ressources partagées


    def handle_connections(self):
        while self.serve:
            client_socket, addr = self.server_socket.accept()
            self.process_client_message(client_socket, addr)
    
    def process_client_message(self, client_socket, addr):


    def handle_signals(self):
        def drought_handler(signum, frame):
            
    

    def update_grass(self, delta):
    #delta = variation de l'herbe
    
    def update_populations(self, delta):
        with self.sem_mutex:
            self.shared_state.nb_preys += delta
            if delta > 0:
                self.sem_prey.release() #Ajouter une proie active
            else:
                self.sem_prey.acquire(blocking = False) #Retirer une proie active
    def cleanup(self):
        self.server_socket.close()


if __name__ == "__main__":
    main()