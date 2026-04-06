from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

from arelab.schemas import ToolExecution
from arelab.util import json_dump, timestamp_slug, utc_now


def command_path(command: str) -> str | None:
    return shutil.which(command)


class ToolRunner:
    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pump_stream(stream, output_path: Path, sink: list[str]) -> None:
        with output_path.open("w", encoding="utf-8", errors="replace") as handle:
            for chunk in iter(stream.readline, ""):
                handle.write(chunk)
                handle.flush()
                sink.append(chunk)
        stream.close()

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
        proc = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        if proc.stdout is None or proc.stderr is None:
            raise RuntimeError("failed to capture subprocess output")
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        stdout_thread = threading.Thread(
            target=self._pump_stream,
            args=(proc.stdout, stdout_path, stdout_chunks),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._pump_stream,
            args=(proc.stderr, stderr_path, stderr_chunks),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            exit_code = proc.wait()
            stderr_chunks.append(f"\n[arelab] command timed out after {timeout} seconds\n")
            with stderr_path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(f"\n[arelab] command timed out after {timeout} seconds\n")
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        finished_at = utc_now()
        execution = ToolExecution(
            label=label,
            command=command,
            cwd=str(cwd or Path.cwd()),
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            log_path=str(log_path),
        )
        json_dump(log_path, json.loads(execution.model_dump_json()))
        if exit_code != 0 and not allow_failure:
            raise RuntimeError(
                f"Command failed ({exit_code}): {' '.join(command)}; see {stderr_path}"
            )
        return execution
