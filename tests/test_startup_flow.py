from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from arelab.ui import create_app


def _repo_fixture(tmp_path: Path) -> Path:
    source_root = Path(__file__).resolve().parents[1]
    repo_root = tmp_path / "repo"
    shutil.copytree(source_root / "config", repo_root / "config")
    shutil.copytree(source_root / "templates", repo_root / "templates")
    shutil.copytree(source_root / "static", repo_root / "static")
    return repo_root


def _created_session_id(repo_root: Path) -> str:
    session_paths = sorted((repo_root / ".state" / "intake-sessions").glob("*.json"))
    assert session_paths
    return session_paths[-1].stem


def test_startup_splash_appears_before_run_ledger(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path)
    client = TestClient(create_app(repo_root, workflow="default"))

    response = client.get("/")

    assert response.status_code == 200
    assert "Shared Intake Routing Splash" in response.text
    assert "Acquire from physical target device" in response.text
    assert "Load saved project" in response.text
    assert "Load reference file or reference file set" in response.text
    assert "The Agency" not in response.text
    assert "Run Ledger" not in response.text


def test_workflow_choice_only_appears_after_intake_context(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path)
    reference = repo_root / "references" / "samfw-a54.zip"
    reference.parent.mkdir(parents=True)
    reference.write_text("sample", encoding="utf-8")
    client = TestClient(create_app(repo_root, workflow="default"))

    response = client.get(
        "/intake/create",
        params={
            "source_type": "reference_file_set",
            "reference_paths": str(reference),
            "acquisition_notes": "downloaded firmware files from SamFW",
        },
    )

    assert response.status_code == 200
    assert "Workflow binding happens only after intake is established." in response.text
    assert "The Agency" in response.text
    assert "The Legion" in response.text
    session_path = repo_root / ".state" / "intake-sessions" / f"{_created_session_id(repo_root)}.json"
    payload = json.loads(session_path.read_text(encoding="utf-8"))
    assert payload["source_type"] == "reference_file_set"
    assert payload["references"][0]["exists"] is True


def test_start_creates_workflow_scoped_basement_outputs_and_preserves_ledger(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path)
    reference = repo_root / "references" / "pixel7-images.zip"
    reference.parent.mkdir(parents=True)
    reference.write_text("sample", encoding="utf-8")
    client = TestClient(create_app(repo_root, workflow="default"))
    client.get(
        "/intake/create",
        params={
            "source_type": "reference_file_set",
            "reference_paths": str(reference),
            "acquisition_notes": "normalized metadata bundles",
        },
    )
    session_id = _created_session_id(repo_root)

    agency_response = client.get(
        "/start",
        params={"session_id": session_id, "workflow_name": "agency"},
        follow_redirects=True,
    )
    legion_response = client.get(
        "/start",
        params={"session_id": session_id, "workflow_name": "legion"},
        follow_redirects=True,
    )
    ledger = client.get("/runs")

    assert agency_response.status_code == 200
    assert legion_response.status_code == 200
    assert "Basement Summary" in agency_response.text
    assert "Basement Summary" in legion_response.text
    assert ledger.status_code == 200
    assert "Run Ledger" in ledger.text

    agency_runs = sorted((repo_root / "runs" / "agency").iterdir())
    legion_runs = sorted((repo_root / "runs" / "legion").iterdir())
    assert len(agency_runs) == 1
    assert len(legion_runs) == 1

    agency_meta = json.loads((agency_runs[0] / "run.json").read_text(encoding="utf-8"))
    legion_meta = json.loads((legion_runs[0] / "run.json").read_text(encoding="utf-8"))
    assert agency_meta["workflow"] == "agency"
    assert legion_meta["workflow"] == "legion"
    assert agency_meta["source_type"] == "reference_file_set"
    assert legion_meta["source_type"] == "reference_file_set"

    agency_basement = agency_runs[0] / "basement" / "intake" / "session-context.json"
    legion_basement = legion_runs[0] / "basement" / "intake" / "session-context.json"
    assert agency_basement.exists()
    assert legion_basement.exists()
    assert agency_runs[0].parent.name == "agency"
    assert legion_runs[0].parent.name == "legion"
