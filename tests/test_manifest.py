from pathlib import Path

from arelab.ingest import build_manifest
from arelab.runner import ToolRunner


def test_manifest_creation(tmp_path: Path) -> None:
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"hello")
    runner = ToolRunner(tmp_path / "logs")
    manifest = build_manifest(sample, tmp_path / "work", {}, runner)
    assert manifest.input_path == str(sample.resolve())
    assert len(manifest.nodes) == 1
    assert manifest.nodes[0].sha256
