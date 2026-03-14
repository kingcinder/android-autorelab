from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from arelab.schemas import ToolExecution
from arelab.util import json_dump, timestamp_slug, utc_now


def command_path(command: str) -> str | None:
    return shutil.which(command)


class ToolRunner:
    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        label: str,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 600,
        allow_failure: bool = False,
    ) -> ToolExecution:
        started_at = utc_now()
        stamp = f"{timestamp_slug()}-{label}"
        stdout_path = self.logs_dir / f"{stamp}.stdout.log"
        stderr_path = self.logs_dir / f"{stamp}.stderr.log"
        log_path = self.logs_dir / f"{stamp}.json"
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout_path.write_text(proc.stdout, encoding="utf-8")
        stderr_path.write_text(proc.stderr, encoding="utf-8")
        finished_at = utc_now()
        execution = ToolExecution(
            label=label,
            command=command,
            cwd=str(cwd or Path.cwd()),
            started_at=started_at,
            finished_at=finished_at,
            exit_code=proc.returncode,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            log_path=str(log_path),
        )
        json_dump(log_path, json.loads(execution.model_dump_json()))
        if proc.returncode != 0 and not allow_failure:
            raise RuntimeError(
                f"Command failed ({proc.returncode}): {' '.join(command)}; see {stderr_path}"
            )
        return execution
