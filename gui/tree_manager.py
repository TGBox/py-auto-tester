from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QMenu, QInputDialog, QMessageBox
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QIcon, QAction
from core.project_manager import ProjectManager

class TreeManagerWidget(QWidget):
    """
    Sidebar Tree view widget managing hierarchy of Routines, Groups, and Tests.
    """
    item_selected_signal = Signal(str, str) # type ('routine'/'group'/'test'), item_id
    run_requested_signal = Signal(str, str) # type, item_id
    record_requested_signal = Signal()

    def __init__(self, project_manager: ProjectManager):
        super().__init__()
        self.pm = project_manager
        self.setup_ui()
        self.refresh_tree()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Header Title
        title_label = QLabel("⚡ TEST-EXPLORER")
        title_label.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 14px;")
        layout.addWidget(title_label)

        # Action Toolbar
        btn_layout = QHBoxLayout()
        
        rec_btn = QPushButton("🔴 Record")
        rec_btn.setObjectName("recordButton")
        rec_btn.setToolTip("Startet Playwright Codegen zur neuen Routine-Aufnahme")
        rec_btn.clicked.connect(lambda: self.record_requested_signal.emit())
        btn_layout.addWidget(rec_btn)

        add_grp_btn = QPushButton("+ Gruppe")
        add_grp_btn.setToolTip("Erstellt eine neue Gruppe aus Routinen")
        add_grp_btn.clicked.connect(self.create_new_group)
        btn_layout.addWidget(add_grp_btn)

        add_test_btn = QPushButton("+ Test")
        add_test_btn.setObjectName("accentButton")
        add_test_btn.setToolTip("Erstellt einen neuen End-to-End Test")
        add_test_btn.clicked.connect(self.create_new_test)
        btn_layout.addWidget(add_test_btn)

        layout.addLayout(btn_layout)

        # Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemSelectionChanged.connect(self.on_item_selection_changed)
        layout.addWidget(self.tree)

    def refresh_tree(self):
        """Reloads tree nodes from ProjectManager."""
        self.tree.clear()

        # Category: Tests
        tests_root = QTreeWidgetItem(self.tree, ["📋 TESTS"])
        tests_root.setExpanded(True)
        tests_root.setData(0, Qt.ItemDataRole.UserRole, {"type": "category_tests"})
        
        tests = self.pm.get_tests()
        for t in tests:
            t_node = QTreeWidgetItem(tests_root, [f"🧪 {t['name']}"])
            t_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "test", "id": t["id"]})
            
            # Show nested items
            for iid in t.get("item_ids", []):
                sub_name = iid
                if iid.startswith("group:"):
                    sub_name = f"📦 Gruppe: {iid.replace('group:', '')}"
                elif iid.startswith("routine:"):
                    sub_name = f"🔧 Routine: {iid.replace('routine:', '')}"
                sub_node = QTreeWidgetItem(t_node, [sub_name])
                sub_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "sub_item", "id": iid})

        # Category: Gruppen
        groups_root = QTreeWidgetItem(self.tree, ["📦 GRUPPEN"])
        groups_root.setExpanded(True)
        groups_root.setData(0, Qt.ItemDataRole.UserRole, {"type": "category_groups"})
        
        groups = self.pm.get_groups()
        for g in groups:
            g_node = QTreeWidgetItem(groups_root, [f"📁 {g['name']}"])
            g_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "group", "id": g["id"]})
            
            for rid in g.get("routine_ids", []):
                r_sub = QTreeWidgetItem(g_node, [f"🔧 {rid}"])
                r_sub.setData(0, Qt.ItemDataRole.UserRole, {"type": "sub_routine", "id": rid})

        # Category: Routinen
        routines_root = QTreeWidgetItem(self.tree, ["🔧 ROUTINEN (Aufgenommen)"])
        routines_root.setExpanded(True)
        routines_root.setData(0, Qt.ItemDataRole.UserRole, {"type": "category_routines"})
        
        routines = self.pm.get_routines()
        for r in routines:
            r_node = QTreeWidgetItem(routines_root, [f"⚡ {r['name']} ({r['id']}.py)"])
            r_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "routine", "id": r["id"]})

    def on_item_selection_changed(self):
        selected = self.tree.selectedItems()
        if not selected:
            return
        item_data = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if item_data and "type" in item_data and "id" in item_data:
            self.item_selected_signal.emit(item_data["type"], item_data["id"])

    def show_context_menu(self, position):
        item = self.tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or "type" not in data:
            return

        menu = QMenu(self)
        item_type = data["type"]
        item_id = data.get("id", "")

        if item_type in ["routine", "group", "test"]:
            run_action = menu.addAction(f"▶ {item_type.capitalize()} Ausführen")
            run_action.triggered.connect(lambda: self.run_requested_signal.emit(item_type, item_id))
            menu.addSeparator()

        if item_type == "routine":
            del_action = menu.addAction("🗑 Routine Löschen")
            del_action.triggered.connect(lambda: self.delete_item("routine", item_id))

        elif item_type == "group":
            edit_action = menu.addAction("✏ Gruppe Bearbeiten")
            edit_action.triggered.connect(lambda: self.edit_group(item_id))
            del_action = menu.addAction("🗑 Gruppe Löschen")
            del_action.triggered.connect(lambda: self.delete_item("group", item_id))

        elif item_type == "test":
            edit_action = menu.addAction("✏ Test Bearbeiten")
            edit_action.triggered.connect(lambda: self.edit_test(item_id))
            del_action = menu.addAction("🗑 Test Löschen")
            del_action.triggered.connect(lambda: self.delete_item("test", item_id))

        menu.exec_(self.tree.viewport().mapToGlobal(position))

    def create_new_group(self):
        routines = self.pm.get_routines()
        if not routines:
            QMessageBox.information(self, "Hinweis", "Bitte nimm zuerst Routinen auf, bevor du eine Gruppe erstellst.")
            return

        name, ok = QInputDialog.getText(self, "Neue Gruppe", "Name der Gruppe:")
        if not ok or not name.strip():
            return

        group_id = name.lower().replace(" ", "_")
        # Default include all current routines or let user select
        r_ids = [r["id"] for r in routines]
        self.pm.save_group(group_id, name, "Erstellte Routine-Gruppe", r_ids)
        self.refresh_tree()

    def edit_group(self, group_id: str):
        groups = self.pm.get_groups()
        group = next((g for g in groups if g["id"] == group_id), None)
        if not group:
            return

        routines = self.pm.get_routines()
        all_rids = [r["id"] for r in routines]
        
        # Simple selection prompt
        msg = f"Routinen für Gruppe '{group['name']}' (kommagetrennt):\nVerfügbar: {', '.join(all_rids)}"
        current_str = ", ".join(group.get("routine_ids", []))
        text, ok = QInputDialog.getText(self, "Gruppe bearbeiten", msg, text=current_str)
        if ok:
            selected_ids = [s.strip() for s in text.split(",") if s.strip() in all_rids]
            self.pm.save_group(group_id, group["name"], group.get("description", ""), selected_ids)
            self.refresh_tree()

    def create_new_test(self):
        name, ok = QInputDialog.getText(self, "Neuer Test", "Name des End-to-End Tests:")
        if not ok or not name.strip():
            return

        test_id = name.lower().replace(" ", "_")
        groups = self.pm.get_groups()
        routines = self.pm.get_routines()

        item_ids = []
        for g in groups:
            item_ids.append(f"group:{g['id']}")
            
        self.pm.save_test(test_id, name, "Automatisch erstellter E2E-Test", item_ids, isolated_session=False)
        self.refresh_tree()

    def edit_test(self, test_id: str):
        tests = self.pm.get_tests()
        test = next((t for t in tests if t["id"] == test_id), None)
        if not test:
            return

        reply = QMessageBox.question(
            self, "Session-Modus",
            "Sollen Routinen im Test isolierte Browser-Sessions nutzen?\n\n"
            "Ja = Isolierte Sessions per Routine\n"
            "Nein = Shared Session (Standard, Logins bleiben erhalten)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No
        )
        isolated = (reply == QMessageBox.StandardButton.Yes)
        
        self.pm.save_test(test_id, test["name"], test.get("description", ""), test.get("item_ids", []), isolated_session=isolated)
        QMessageBox.information(self, "Gespeichert", f"Test '{test['name']}' aktualisiert (Isoliert={isolated}).")

    def delete_item(self, item_type: str, item_id: str):
        reply = QMessageBox.question(
            self, "Löschen bestätigen",
            f"Möchtest du dieses Element wirklich löschen?\nTyp: {item_type}, ID: {item_id}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if item_type == "routine":
                self.pm.delete_routine(item_id)
            elif item_type == "group":
                self.pm.delete_group(item_id)
            elif item_type == "test":
                self.pm.delete_test(item_id)
            self.refresh_tree()
