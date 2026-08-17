import sys
import os
sys.path.insert(0, os.path.abspath("."))
import time
from PySide6.QtCore import QCoreApplication
from core.project_manager import ProjectManager
from core.execution_engine import ExecutionEngineWorker

def main():
    app = QCoreApplication(sys.argv)
    pm = ProjectManager("project_data")

    # Create a test routine that opens wikipedia and waits 2s
    pm.save_routine("test_close_wiki", "Wiki Close Test", "Test", """def execute(page, vars):
        page.goto('https://www.wikipedia.org')
        page.get_by_role('link', name='Deutsch').click()
    """)

    print("Starting worker thread...")
    worker = ExecutionEngineWorker(pm, "routine", "test_close_wiki", headed=True, speed_mode="fastest", auto_close=True)

    def on_log(msg):
        print(f"[WORKER LOG] {msg}")

    def on_finished(succ, msg):
        print(f"[WORKER FINISHED] success={succ}, msg={msg}")
        app.quit()

    worker.log_signal.connect(on_log)
    worker.finished_signal.connect(on_finished)

    worker.start()
    app.exec()

    print("Script end. Checking if browser process is still open...")
    time.sleep(3)

if __name__ == "__main__":
    main()

