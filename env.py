import os
import random
import threading 
import socket
import signal
import multiprocessing
from multiprocessing import shared_memory, Semaphore, Queue 

#structure représntation population
class Population:

    def __init__(self, name, size, energy, is_active):
        self.name = name
        self.size = size
        self.energy = energy 
        self.is_active = is_active


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

        #planifie une sécheresse aléatoire 
        self.schedule_random_drought()

        connection_thread.join()
        signal_thread.join()

        self.cleanup() #ferme les connexions et libère les ressources partagées

    def schedule_random_drought(self):
        #Génère un délai aléatoire entre 15 et 60 secondes
        delay_seconds = random.randint(15, 60)

        drought_timer = threading.Timer(delay_seconds, self.trigger_drought)
        drought_timer.start()

    def trigger_drought(self):
        if self.serve:
            os.kill(os.getpid(), signal.SIGUSR1)  # Envoyer le signal SIGUSR1
            
    def handle_signals(self):
        def drought_handler(signum, frame):
            with self.sem_mutex:
                self.shared_state.drought = True
                self.shared_state.grass *= 0.5
                if self.serve:
                    self.schedule_random_drought()  # Planifier une nouvelle sécheresse

        signal.signal(signal.SIGUSR1, drought_handler)

        while self.serve:
            signal.pause()  # Attend un signal
    
    def handle_connections(self):
        while self.serve:
            client_socket, addr = self.server_socket.accept()
            self.process_client_message(client_socket, addr)
    
    def process_client_message(self, client_socket, addr):
            with client_socket:
                data = client_socket.recv(1024).decode()
                if data == "stop":
                    self.serve = False  # Arrêter le serveur
                elif data == "je mange":
                    self.update_grass(-1)  # Décrémenter l'herbe
                elif data == "je meurs":
                    self.update_population(-1)  # Décrémenter la population
                elif data == "je me reproduis":
                    self.update_population(1)  # Incrémenter la population



        
    

    def update_grass(self, delta):
    #delta = variation de l'herbe
        with self.sem_mutex:
            self.shared_state.grass += delta
            self.sem_grass.release() if delta > 0 else  None #Met à jour le sémaphore herbe
    
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