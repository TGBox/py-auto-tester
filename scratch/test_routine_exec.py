import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication
from core.project_manager import ProjectManager
from core.execution_engine import ExecutionEngineWorker

app = QCoreApplication(sys.argv)

project_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(project_dir)

pm = ProjectManager(os.path.join(parent_dir, "project_data"))

worker = ExecutionEngineWorker(
    project_manager=pm,
    mode="routine",
    item_id="test_login__termin__best_tigung__l_schen_und_logout",
    headed=False, # run headless for verification
    speed_mode="fastest"
)

def on_log(msg):
    print(msg, flush=True)

def on_finished(success, summary, report_path):
    print(f"FINISHED: success={success}, summary={summary}, report={report_path}", flush=True)
    app.quit()

worker.log_signal.connect(on_log)
worker.finished_signal.connect(on_finished)
worker.start()

sys.exit(app.exec())
