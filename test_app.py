import os
import pytest
import shutil
from core.project_manager import ProjectManager

@pytest.fixture
def temp_pm(tmp_path):
    test_dir = os.path.join(tmp_path, "test_proj")
    pm = ProjectManager(test_dir)
    return pm

def test_project_manager_crud(temp_pm):
    # Routines
    rid = temp_pm.save_routine("test_rec", "Test Routine", "Desc", "def execute(page, vars):\n    pass")
    assert rid == "test_rec"
    routines = temp_pm.get_routines()
    assert len(routines) == 1
    assert routines[0]["id"] == "test_rec"

    # Groups
    temp_pm.save_group("grp1", "Group 1", "Desc", ["test_rec"])
    groups = temp_pm.get_groups()
    assert len(groups) == 1
    assert groups[0]["id"] == "grp1"

    # Tests
    temp_pm.save_test("t1", "Test 1", "Desc", ["group:grp1"], isolated_session=False)
    tests = temp_pm.get_tests()
    assert len(tests) == 1
    assert tests[0]["id"] == "t1"

    # Delete
    temp_pm.delete_routine("test_rec")
    assert len(temp_pm.get_routines()) == 0
