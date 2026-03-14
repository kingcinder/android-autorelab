from arelab.locks import clear_workflow_lock, read_active_workflow, workflow_lock


def test_workflow_lock_roundtrip() -> None:
    clear_workflow_lock()
    with workflow_lock("agency", "test-suite"):
        active = read_active_workflow()
        assert active
        assert active["workflow"] == "agency"
    assert read_active_workflow() is None
