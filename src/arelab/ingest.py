from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from arelab.runner import ToolRunner
from arelab.schemas import ArtifactManifest, ArtifactNode
from arelab.util import sha256_file, utc_now


def _kind_for(path: Path) -> str:
    name = path.name.lower()
    if path.is_dir():
        return "directory"
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".img"):
        if "super" in name:
            return "super_image"
        if "boot" in name:
            return "boot_image"
        return "partition_image"
    if name.endswith((".bin", ".elf", ".so", ".apk", ".jar")):
        return "binary"
    return "file"


def _node_for(path: Path, *, source: str | None = None, derived_from: list[str] | None = None) -> ArtifactNode:
    mime, _ = mimetypes.guess_type(str(path))
    return ArtifactNode(
        path=str(path),
        kind=_kind_for(path),
        mime=mime,
        sha256=sha256_file(path) if path.is_file() else None,
        size=path.stat().st_size if path.exists() and path.is_file() else None,
        source=source,
        derived_from=derived_from or [],
    )


def build_manifest(input_path: Path, work_dir: Path, tools: dict[str, str | None], runner: ToolRunner) -> ArtifactManifest:
    nodes: list[ArtifactNode] = []
    input_path = input_path.resolve()
    if input_path.is_dir():
        for path in sorted(input_path.rglob("*")):
            if path.is_file():
                nodes.append(_node_for(path, source="input"))
    elif input_path.is_file():
        nodes.append(_node_for(input_path, source="input"))
        lowered = input_path.name.lower()
        if lowered.endswith(".zip"):
            unpack_dir = work_dir / "unzipped" / input_path.stem
            unpack_dir.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(input_path), str(unpack_dir))
            for path in sorted(unpack_dir.rglob("*")):
                if path.is_file():
                    nodes.append(_node_for(path, source="unzip", derived_from=[str(input_path)]))
        elif lowered.endswith(".img") and "super" in lowered and tools.get("lpunpack"):
            extract_dir = work_dir / "lpunpack" / input_path.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            runner.run(
                "lpunpack",
                [tools["lpunpack"], str(input_path), str(extract_dir)],
                allow_failure=True,
            )
            for path in sorted(extract_dir.rglob("*")):
                if path.is_file():
                    nodes.append(_node_for(path, source="lpunpack", derived_from=[str(input_path)]))
        elif lowered.endswith(".img") and "boot" in lowered and tools.get("unpack_bootimg"):
            extract_dir = work_dir / "bootimg" / input_path.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            runner.run(
                "unpack_bootimg",
                [tools["unpack_bootimg"], "--input", str(input_path), "--out", str(extract_dir)],
                allow_failure=True,
            )
            for path in sorted(extract_dir.rglob("*")):
                if path.is_file():
                    nodes.append(_node_for(path, source="unpack_bootimg", derived_from=[str(input_path)]))
        elif lowered.endswith(".img") and tools.get("simg2img"):
            unsparse = work_dir / "simg2img" / f"{input_path.stem}.raw.img"
            unsparse.parent.mkdir(parents=True, exist_ok=True)
            runner.run(
                "simg2img",
                [tools["simg2img"], str(input_path), str(unsparse)],
                allow_failure=True,
            )
            if unsparse.exists():
                nodes.append(_node_for(unsparse, source="simg2img", derived_from=[str(input_path)]))
        elif tools.get("binwalk") and input_path.suffix.lower() in {".bin", ".img"}:
            extract_root = work_dir / "binwalk"
            extract_root.mkdir(parents=True, exist_ok=True)
            runner.run(
                "binwalk",
                [tools["binwalk"], "--extract", "--directory", str(extract_root), str(input_path)],
                allow_failure=True,
            )
            for path in sorted(extract_root.rglob("*")):
                if path.is_file():
                    nodes.append(_node_for(path, source="binwalk", derived_from=[str(input_path)]))
    return ArtifactManifest(input_path=str(input_path), created_at=utc_now(), nodes=nodes)
