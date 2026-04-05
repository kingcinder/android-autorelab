from __future__ import annotations

import argparse
import json
from pathlib import Path

from arelab.config import load_yaml
from arelab.schemas import TargetProfile, TargetScore
from arelab.util import json_dump, slugify


def canonical_target_keys(profile: TargetProfile) -> dict[str, str]:
    vendor_key = slugify(profile.vendor)
    model_key = slugify(profile.model)
    build_key = slugify(profile.build_id)
    artifact_key = slugify("-".join(artifact.name for artifact in profile.artifacts) or profile.target_id)
    return {
        "device_key": f"{vendor_key}-{model_key}",
        "build_key": f"{vendor_key}-{build_key}",
        "artifact_key": f"{vendor_key}-{artifact_key}",
    }


def normalize_target_profile(profile: TargetProfile) -> dict[str, object]:
    return {
        "target_id": profile.target_id,
        "vendor": profile.vendor,
        "family": profile.family,
        "model": profile.model,
        "build_id": profile.build_id,
        "canonical_keys": canonical_target_keys(profile),
        "artifact_count": len(profile.artifacts),
        "boot_component_count": len(profile.boot_components),
        "authorized_scope": profile.authorized_scope,
        "metadata": profile.metadata,
    }


def _candidate_paths(config_paths: list[Path], config_dir: Path | None = None) -> list[Path]:
    results: list[Path] = []
    if config_dir is not None:
        results.extend(sorted(config_dir.glob("*.yaml")))
        results.extend(sorted(config_dir.glob("*.yml")))
    results.extend(config_paths)
    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in results:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def load_target_profile(path: Path) -> TargetProfile:
    payload = load_yaml(path)
    if not payload:
        raise FileNotFoundError(f"target config missing or empty: {path}")
    return TargetProfile.model_validate(payload)


def load_target_profiles(config_paths: list[Path], config_dir: Path | None = None) -> list[TargetProfile]:
    return [load_target_profile(path) for path in _candidate_paths(config_paths, config_dir)]


def load_target_profile_by_id(target_id: str, config_paths: list[Path], config_dir: Path | None = None) -> TargetProfile:
    for path in _candidate_paths(config_paths, config_dir):
        profile = load_target_profile(path)
        if profile.target_id == target_id:
            return profile
    raise FileNotFoundError(f"target_id not found in YAML content: {target_id}")


def score_target(profile: TargetProfile) -> TargetScore:
    rationale = {
        "vendor_weight": profile.vendor_weight * 20.0,
        "bootchain_depth": float(profile.bootchain_depth) * 8.0,
        "artifact_completeness": profile.artifact_completeness * 30.0,
        "recency_rank": float(profile.recency_rank) * 4.0,
        "disclosure_value": float(profile.disclosure_value) * 6.0,
        "artifact_count": float(len(profile.artifacts)) * 2.0,
    }
    score = round(sum(rationale.values()), 2)
    return TargetScore(target_id=profile.target_id, score=score, rationale=rationale)


def rank_targets(profiles: list[TargetProfile]) -> list[TargetScore]:
    return sorted((score_target(profile) for profile in profiles), key=lambda item: (-item.score, item.target_id))


def _write_or_print(payload: object, output: Path | None) -> None:
    if output is not None:
        json_dump(output, payload)
        return
    print(json.dumps(payload, indent=2))


def main_intake_target() -> int:
    parser = argparse.ArgumentParser(description="Normalize authorized target configs into canonical target metadata.")
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--target-id", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    config_paths = [Path(value) for value in args.config]
    config_dir = Path(args.config_dir) if args.config_dir else None
    output = Path(args.output) if args.output else None
    if args.target_id:
        profile = load_target_profile_by_id(args.target_id, config_paths, config_dir)
        _write_or_print(normalize_target_profile(profile), output)
        return 0
    payload = [normalize_target_profile(profile) for profile in load_target_profiles(config_paths, config_dir)]
    _write_or_print(payload, output)
    return 0


def main_score_targets() -> int:
    parser = argparse.ArgumentParser(description="Score authorized targets for defensive boot-chain research priority.")
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    config_paths = [Path(value) for value in args.config]
    config_dir = Path(args.config_dir) if args.config_dir else None
    output = Path(args.output) if args.output else None
    ranked = [item.model_dump(mode="json") for item in rank_targets(load_target_profiles(config_paths, config_dir))]
    _write_or_print(ranked, output)
    return 0
