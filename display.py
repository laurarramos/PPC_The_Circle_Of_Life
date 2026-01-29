import cmd
import time
import sys
import threading 
from typing import Any, Optional, Dict
from queue import Empty
import subprocess 


from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QSpinBox)
from PySide6.QtCore import QThread, Signal, Slot
from multiprocessing.managers import BaseManager

HOST = "localhost"
MANAGER_PORT = 50000
AUTHKEY = b"llave"

class EnvManager(BaseManager):
    pass

EnvManager.register("get_d_to_env")
EnvManager.register("get_env_to_d")


class CommWorker(QThread):
    """
    Thread dédié à la réception des messages depuis env.
    Communique avec l'UI via des signaux Qt.

    """
    data_received = Signal(dict)  # Signal pour envoyer le dictionnaire d'état à l'UI

    def __init__(self,mq_from_env):
        super().__init__()
        self.mq_from_env = mq_from_env
        self.running = True

    def run(self):
        """
        Boucle de lecture de la file de messages.
        """
        while self.running:
            try:
                msg = self.mq_from_env.get(timeout=0.1)  
    
                self.data_received.emit(msg)  # Envoie vers le thread principal
            except Empty:
                continue  
            except Exception as e:
                print(f"[Thread CommWorker] Error: {e}")
                break 

    def stop(self):
        self.running = False


class DisplayWindow(QWidget):
    """
    Interface graphique tournant dans le thread principal.
    """
    def __init__(self, mq_to_env: Any, mq_from_env:Any):
        super().__init__()
        self.mq_to_env = mq_to_env
        self.mq_from_env = mq_from_env

        self.init_ui()

        self.comm_thread = CommWorker(self.mq_from_env)
        self.comm_thread.data_received.connect(self.update_data) #Connexion du signal     
        self.comm_thread.start()

    def init_ui(self):
        self.setWindowTitle("Simulation - The Circle of Life")
        self.resize(600, 400)
        layout = QVBoxLayout()

        self.status_label = QLabel("Waiting for the first snapshot...")
        self.status_label.setStyleSheet("padding: 15px; background: #f0f0f0; border-radius: 5px;")
        layout.addWidget(self.status_label)

        # Ajout des contrôles
        layout.addLayout(self.create_control_row("Grass:", "SET_GRASS"))
        layout.addLayout(self.create_control_row("Treshold of reproduction R:", "SET_R"))
        layout.addLayout(self.create_control_row("Treshold of hunger H:", "SET_H"))

        row_add = QHBoxLayout()
        self.add_prey_btn = QPushButton(" + Add Prey ")
        self.add_pred_btn = QPushButton(" + Add Predator ")
        
        # Lancement du processus par display.py
        self.add_prey_btn.clicked.connect(self.spawn_prey)
        self.add_pred_btn.clicked.connect(self.spawn_predator)
        
        row_add.addWidget(self.add_prey_btn)
        row_add.addWidget(self.add_pred_btn)
        layout.addLayout(row_add)


        self.stop_btn = QPushButton("STOP SIMULATION")
        self.stop_btn.clicked.connect(self.close_application)
        layout.addWidget(self.stop_btn)

        self.setLayout(layout)

    def create_control_row(self, label_text: str, cmd: str):
        row = QHBoxLayout()
        spin = QSpinBox()
        spin.setRange(0, 500)
        btn = QPushButton("Apply")
        btn.clicked.connect(lambda: self.mq_to_env.put({"cmd": cmd, "value": spin.value()}))
        row.addWidget(QLabel(label_text))
        row.addWidget(spin)
        row.addWidget(btn)
        return row
    def spawn_prey(self):
        """Lance un nouveau processus proie."""
        subprocess.Popen([sys.executable, "prey.py"])

    def spawn_predator(self):
        """Lance un nouveau processus prédateur."""
        subprocess.Popen([sys.executable, "predator.py"])

    @Slot(dict)
    def update_data(self, msg):
        """Transforme le dictionnaire en une liste HTML."""
        html_text = "<div style='font-family: Arial; font-size: 14px;'>"
        html_text += "<h3 style='color: #2c3e50; margin-bottom: 10px;'>État de la Simulation</h3>"
        html_text += "<ul style='list-style-type: none; padding-left: 0;'>"
        for key, value in msg.items():
            label = key.replace("_", " ").capitalize()
            html_text += f"""
                <li style='padding: 5px 0; border-bottom: 1px solid #eee;'>
                    <b style='color: #2980b9;'>{label} :</b> 
                    <span style='float: right; color: #27ae60; font-weight: bold;'>{value}</span>
                </li>
                """
        html_text += "</ul></div>"
        self.status_label.setText(html_text)

    def close_application(self):
            """Envoie STOP et ferme la fenêtre."""
            try:
                self.mq_to_env.put({"cmd": "STOP"})
            except:
                pass
            self.close()
            
    def closeEvent(self, event):
            """Assure la fermeture propre du thread."""
            self.comm_thread.stop()
            self.comm_thread.wait()
            super().closeEvent(event)

def display_main():
    """
    Point d'entrée du processus display, utilise l'application Qt.
    """
    app = QApplication(sys.argv)

    try: 
        manager = EnvManager(address=(HOST, MANAGER_PORT), authkey=AUTHKEY)
        manager.connect()
        mq_to_env = manager.get_d_to_env()
        mq_from_env = manager.get_env_to_d()

        window = DisplayWindow(mq_to_env, mq_from_env)
        window.show()

        sys.exit(app.exec())
    except Exception as e:
        print(f"[Display] Connection error to the manager: {e}")
        sys.exit(1)


if __name__ == "__main__":
    display_main()