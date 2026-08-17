import sys
import os
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow

def seed_demo_data(project_dir: str = "project_data"):
    """Seeds initial demo routine and test structure based on login test if empty."""
    routines_dir = os.path.join(project_dir, "routines")
    os.makedirs(routines_dir, exist_ok=True)

    demo_routine_path = os.path.join(routines_dir, "demo_login.py")
    if not os.path.exists(demo_routine_path):
        sample_code = (
            "# ROUTINE_NAME: Demo Login & Terminplaner\n"
            "# ROUTINE_DESC: Logged sich im AL Dashboard ein und öffnet Terminplaner.\n\n"
            "def execute(page, vars):\n"
            "    base_url = vars.get('BASE_URL', 'https://dr.data-al.cloud/aldashboard/login?returnUrl=%2Fhome')\n"
            "    username = vars.get('USERNAME', 'admin@demo.de')\n"
            "    password = vars.get('PASSWORD', 'danitest')\n\n"
            "    page.goto(base_url)\n"
            "    page.get_by_role('textbox', name='E-Mail').click()\n"
            "    page.get_by_role('textbox', name='E-Mail').fill(username)\n"
            "    page.get_by_role('textbox', name='E-Mail').press('Tab')\n"
            "    page.get_by_role('textbox', name='Passwort').fill(password)\n"
            "    page.get_by_role('textbox', name='Passwort').press('Tab')\n"
            "    page.get_by_role('button').filter(has_text='check').click()\n"
            "    page.get_by_role('link', name='Terminplaner').click()\n"
        )
        with open(demo_routine_path, "w", encoding="utf-8") as f:
            f.write(sample_code)

def main():
    seed_demo_data("project_data")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow("project_data")
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
