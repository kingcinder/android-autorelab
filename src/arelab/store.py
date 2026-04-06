from __future__ import annotations

from pathlib import Path

from arelab.schemas import RunMetadata
from arelab.util import json_dump, timestamp_slug, utc_now


class ArtifactStore:
    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        input_path: Path,
        profile: str,
        workflow: str,
        *,
        model_overrides: dict[str, str] | None = None,
    ) -> tuple[str, Path]:
        run_id = timestamp_slug()
        run_dir = self.runs_root / run_id
        for name in ("logs", "artifacts", "reports", "prompts", "checkpoints", "work", "basement"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        metadata = RunMetadata(
            run_id=run_id,
            workflow=workflow,
            status="running",
            created_at=utc_now(),
            updated_at=utc_now(),
            input_path=str(input_path),
            output_root=str(run_dir),
            profile=profile,
            stage="created",
            basement_path=str(run_dir / "basement"),
            model_overrides=model_overrides or {},
        )
        self.write_metadata(run_dir, metadata)
        return run_id, run_dir

    @staticmethod
    def metadata_path(run_dir: Path) -> Path:
        return run_dir / "run.json"

    def write_metadata(self, run_dir: Path, metadata: RunMetadata) -> None:
        metadata.updated_at = utc_now()
        json_dump(self.metadata_path(run_dir), metadata.model_dump(mode="json"))

    def load_metadata(self, run_dir: Path) -> RunMetadata:
        import json

        with self.metadata_path(run_dir).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return RunMetadata.model_validate(payload)
