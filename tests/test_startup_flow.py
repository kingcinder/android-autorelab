from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from arelab.model_gateway import ModelGateway
from arelab.ui import create_app
from arelab.util import utc_now


def _repo_fixture(tmp_path: Path) -> Path:
    source_root = Path(__file__).resolve().parents[1]
    repo_root = tmp_path / "repo"
    shutil.copytree(source_root / "config", repo_root / "config")
    shutil.copytree(source_root / "templates", repo_root / "templates")
    shutil.copytree(source_root / "static", repo_root / "static")
    (repo_root / "config" / "local-overrides.yaml").unlink(missing_ok=True)
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
    assert "Start with what you already have." in response.text
    assert "Step 1 of 3" in response.text
    assert "Acquire from physical target device" in response.text
    assert "Load saved project" in response.text
    assert "Load reference file or reference file set" in response.text
    assert "Start with The Agency" not in response.text
    assert "Start with The Legion" not in response.text
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
    assert "Review the intake, then choose how you want to work." in response.text
    assert "Step 2 of 3" in response.text
    assert "The Agency" in response.text
    assert "The Legion" in response.text
    assert "Choose models for this run" in response.text
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
    assert "Basement summary" in agency_response.text
    assert "Basement summary" in legion_response.text
    assert ledger.status_code == 200
    assert "Run Ledger" in ledger.text
    assert "Start a new run" in ledger.text

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


def test_live_endpoint_and_operator_console_are_available(tmp_path: Path, monkeypatch) -> None:
    repo_root = _repo_fixture(tmp_path)
    reference = repo_root / "references" / "session.json"
    reference.parent.mkdir(parents=True)
    reference.write_text("sample", encoding="utf-8")
    client = TestClient(create_app(repo_root, workflow="default"))
    client.get(
        "/intake/create",
        params={
            "source_type": "reference_file_set",
            "reference_paths": str(reference),
            "acquisition_notes": "interactive run check",
        },
    )
    session_id = _created_session_id(repo_root)
    client.get(
        "/start",
        params={"session_id": session_id, "workflow_name": "agency"},
        follow_redirects=True,
    )
    run_dir = sorted((repo_root / "runs" / "agency").iterdir())[0]
    run_id = run_dir.name

    live = client.get(f"/api/runs/agency/{run_id}/live")
    assert live.status_code == 200
    payload = live.json()
    assert payload["run"]["workflow"] == "agency"
    assert "latest_log" in payload
    assert "console_history" in payload

    def fake_chat_text(self: ModelGateway, *, prompt: str, model=None, role="planner", system_prompt="", temperature=0.0, max_tokens=0, timeout=0, save_guidance=False):
        record = {
            "recorded_at": utc_now(),
            "model": model or "stub-model",
            "role": role,
            "prompt": prompt,
            "response": "Stub reply",
            "save_guidance": save_guidance,
        }
        self._log_console_exchange(record)
        if save_guidance:
            self.append_operator_guidance(prompt)
        return {"model": record["model"], "response": record["response"], "recorded_at": record["recorded_at"]}

    monkeypatch.setattr(ModelGateway, "chat_text", fake_chat_text)
    response = client.post(
        f"/api/runs/agency/{run_id}/console",
        json={"prompt": "Please focus on bootloader policy drift.", "save_guidance": True},
    )
    assert response.status_code == 200
    console_payload = response.json()
    assert console_payload["response"] == "Stub reply"

    live_after = client.get(f"/api/runs/agency/{run_id}/live")
    assert live_after.status_code == 200
    assert live_after.json()["console_history"][-1]["prompt"] == "Please focus on bootloader policy drift."


def test_startup_splash_skips_incomplete_run_metadata(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path)
    broken_run = repo_root / "runs" / "agency" / "broken-run"
    broken_run.mkdir(parents=True)
    (broken_run / "run.json").write_text("", encoding="utf-8")
    client = TestClient(create_app(repo_root, workflow="default"))

    response = client.get("/")

    assert response.status_code == 200
    assert "Start with what you already have." in response.text
