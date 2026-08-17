import sys
import os
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtCore import QCoreApplication
from core.project_manager import ProjectManager
from core.execution_engine import ExecutionEngineWorker

def main():
    app = QCoreApplication(sys.argv)
    pm = ProjectManager("project_data")

    routines = pm.get_routines()
    print(f"Routines found: {[r['id'] for r in routines]}")

    if routines:
        target_id = routines[0]['id']
        print(f"Running worker for routine: {target_id}")

        worker = ExecutionEngineWorker(pm, "routine", target_id, headed=True, speed_mode="fastest", auto_close=True)
        worker.log_signal.connect(lambda msg: print(f"[LOG] {msg}"))
        worker.finished_signal.connect(lambda succ, msg: (print(f"[FINISHED] success={succ}, msg={msg}"), app.quit()))

        worker.start()
        app.exec()

    print("Execution completed successfully.")

if __name__ == "__main__":
    main()

