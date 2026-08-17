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

def test_execution_engine_speed_modes(temp_pm):
    from core.execution_engine import ExecutionEngineWorker
    worker_fast = ExecutionEngineWorker(temp_pm, "routine", "test_rec", speed_mode="fastest")
    assert worker_fast.get_slow_mo_ms() == 0

    worker_normal = ExecutionEngineWorker(temp_pm, "routine", "test_rec", speed_mode="normal")
    assert worker_normal.get_slow_mo_ms() == 300

    worker_slow = ExecutionEngineWorker(temp_pm, "routine", "test_rec", speed_mode="slow")
    assert worker_slow.get_slow_mo_ms() == 1000

    worker_step = ExecutionEngineWorker(temp_pm, "routine", "test_rec", speed_mode="step")
    assert worker_step.get_slow_mo_ms() == 2500

def test_execution_engine_browser_and_device_profiles(temp_pm):
    from core.execution_engine import ExecutionEngineWorker
    
    worker_ff = ExecutionEngineWorker(temp_pm, "routine", "test_rec", browser_engine="firefox", device_profile="iphone_14")
    assert worker_ff.browser_engine == "firefox"
    assert worker_ff.device_profile == "iphone_14"

    opts = ExecutionEngineWorker.get_context_options("iphone_14")
    assert opts["viewport"] == {"width": 390, "height": 844}
    assert opts["is_mobile"] is True
    assert opts["has_touch"] is True

    opts_desk = ExecutionEngineWorker.get_context_options("desktop_1080p")
    assert opts_desk["viewport"] == {"width": 1920, "height": 1080}


