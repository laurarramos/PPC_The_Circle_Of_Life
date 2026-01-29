# The Circle of Life

Ce projet est une simulation multi-processus d'un écosystème composé de proies et de prédateurs. Elle s'appuie sur une architecture décentralisée basée sur les sockets, les message queues et la mémoire partagée.

## Bibliothèques 
Le projet utilise les bibliothèques Python suivantes :

- Dépendance externe :
    - `PySide6` : pour l'interface graphique. Doit être installée via `pip install PySide6`.

- Bibliothèques standard de Python :
    - `multiprocessing` et `threading` : pour la gestion des processus indépendants et le parallélisme.
    - `socket` et `json` : pour la communication entre les processus.
    - `subprocess` : pour le lancement dynamique de nouveaux processus proies/prédateurs.

## Lancement de la simulation

1. Assurez-vous d'avoir installé `PySide6` si vous souhaitez utiliser l'interface graphique.
2. Exécutez le script `env.py` pour démarrer l'environnement.
3. Exécutez le script `display.py` pour lancer l'interface graphique de la simulation.
4. Utilisez l'interface graphique pour introduire de l'herbe, définir H et R, et ajouter des proies et des prédateurs à la simulation.
5. Pour arrêter la simulation, utilisez le bouton "STOP SIMULATION" dans l'interface graphique.

## Nettoyage du système

En cas d'arrêt brutal, vous pouvez nettoyer les processus Python en cours d'exécution via la commande suivante dans le terminal :
- Windows (PowerShell) : `stop-process -name "python*"`
- Linux/Mac : `pkill -f python3`