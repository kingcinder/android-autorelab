from arelab.locks import clear_workflow_lock, read_active_workflow, workflow_lock


def test_workflow_lock_roundtrip() -> None:
    clear_workflow_lock()
    with workflow_lock("agency", "test-suite"):
        active = read_active_workflow("agency")
        assert active
        assert active["workflow"] == "agency"
    assert read_active_workflow("agency") is None


def test_workflow_locks_are_scoped_per_workflow() -> None:
    clear_workflow_lock()
    with workflow_lock("agency", "test-suite"):
        with workflow_lock("legion", "test-suite"):
            agency = read_active_workflow("agency")
            legion = read_active_workflow("legion")
            assert agency
            assert legion
            assert agency["workflow"] == "agency"
            assert legion["workflow"] == "legion"
