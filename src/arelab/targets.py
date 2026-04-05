from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from arelab.config import load_yaml
from arelab.schemas import (
    ABPartitionVerification,
    BootEnvironmentFingerprint,
    FingerprintSignal,
    SlotPartitionSummary,
    SlotVerificationIssue,
    TargetProfile,
    TargetScore,
)
from arelab.util import json_dump, slugify


BOOTLOADER_PATTERNS = [
    re.compile(r"androidboot\.bootloader=([^\s]+)", re.IGNORECASE),
    re.compile(r"(?<!\.)\bbootloader(?: version)?[:=\s]+([A-Za-z0-9._-]+)", re.IGNORECASE),
    re.compile(r"\b(?:abl|xbl|lk|sboot) version[:=\s]+([A-Za-z0-9._-]+)", re.IGNORECASE),
]
LOCK_PATTERNS = [
    (re.compile(r"androidboot\.flash\.locked=1", re.IGNORECASE), "locked", 0.95, "kernel cmdline reports locked flash state"),
    (re.compile(r"androidboot\.flash\.locked=0", re.IGNORECASE), "unlocked", 0.95, "kernel cmdline reports unlocked flash state"),
    (re.compile(r"\bdevice state[:=\s]+locked\b", re.IGNORECASE), "locked", 0.75, "boot log reports locked device state"),
    (re.compile(r"\bdevice state[:=\s]+unlocked\b", re.IGNORECASE), "unlocked", 0.75, "boot log reports unlocked device state"),
]
VERIFIED_BOOT_PATTERNS = [
    (re.compile(r"androidboot\.verifiedbootstate=(green|yellow|orange|red)", re.IGNORECASE), 0.95, "kernel cmdline reports verified boot state"),
    (re.compile(r"\bverified boot state[:=\s]+(green|yellow|orange|red)\b", re.IGNORECASE), 0.75, "boot log reports verified boot state"),
]
SLOT_PATTERNS = [
    re.compile(r"androidboot\.slot_suffix=_?([ab])", re.IGNORECASE),
    re.compile(r"\bslot suffix[:=\s]+_?([ab])\b", re.IGNORECASE),
]


def _metadata_texts(profile: TargetProfile, key: str) -> list[str]:
    value = profile.metadata.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [json.dumps(value, sort_keys=True)]


def _metadata_dict(profile: TargetProfile, key: str) -> dict[str, object]:
    value = profile.metadata.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _record_signal(
    signals: list[FingerprintSignal],
    source: str,
    key: str,
    value: str,
    confidence: float,
    rationale: str,
) -> None:
    signals.append(
        FingerprintSignal(
            source=source,
            key=key,
            value=value,
            confidence=confidence,
            rationale=rationale,
        )
    )


def _pick_state(scores: dict[str, float], *, unknown: str, mixed: str | None = None) -> str:
    if not scores:
        return unknown
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if mixed is not None and len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 0.25:
        return mixed
    return ranked[0][0]


def _score_slot(partitions: dict[str, object], key: str) -> str | None:
    value = partitions.get(key)
    if value is None:
        return None
    return str(value)


def _slot_suffix_from_sources(profile: TargetProfile) -> str | None:
    for source_key in ("kernel_cmdline", "boot_logs"):
        for text in _metadata_texts(profile, source_key):
            for pattern in SLOT_PATTERNS:
                match = pattern.search(text)
                if match:
                    return match.group(1).lower()
    return None


def fingerprint_boot_environment(profile: TargetProfile) -> BootEnvironmentFingerprint:
    evidence: list[FingerprintSignal] = []
    heuristics: list[str] = []
    version_scores: dict[str, float] = {}
    lock_scores: dict[str, float] = {}
    verified_scores: dict[str, float] = {}

    for text in _metadata_texts(profile, "boot_logs"):
        for pattern in BOOTLOADER_PATTERNS:
            for match in pattern.finditer(text):
                version = match.group(1)
                version_scores[version] = version_scores.get(version, 0.0) + 0.7
                _record_signal(evidence, "boot_log", "bootloader_version", version, 0.7, "boot log bootloader heuristic matched")
        for pattern, state, confidence, rationale in LOCK_PATTERNS:
            if pattern.search(text):
                lock_scores[state] = lock_scores.get(state, 0.0) + confidence
                _record_signal(evidence, "boot_log", "device_lock_state", state, confidence, rationale)
        for pattern, confidence, rationale in VERIFIED_BOOT_PATTERNS:
            match = pattern.search(text)
            if match:
                state = match.group(1).lower()
                verified_scores[state] = verified_scores.get(state, 0.0) + confidence
                _record_signal(evidence, "boot_log", "verified_boot_state", state, confidence, rationale)

    for text in _metadata_texts(profile, "kernel_cmdline"):
        for pattern in BOOTLOADER_PATTERNS:
            for match in pattern.finditer(text):
                version = match.group(1)
                version_scores[version] = version_scores.get(version, 0.0) + 0.95
                _record_signal(evidence, "kernel_cmdline", "bootloader_version", version, 0.95, "kernel cmdline bootloader heuristic matched")
        for pattern, state, confidence, rationale in LOCK_PATTERNS:
            if pattern.search(text):
                lock_scores[state] = lock_scores.get(state, 0.0) + confidence
                _record_signal(evidence, "kernel_cmdline", "device_lock_state", state, confidence, rationale)
        for pattern, confidence, rationale in VERIFIED_BOOT_PATTERNS:
            match = pattern.search(text)
            if match:
                state = match.group(1).lower()
                verified_scores[state] = verified_scores.get(state, 0.0) + confidence
                _record_signal(evidence, "kernel_cmdline", "verified_boot_state", state, confidence, rationale)

    for register, raw_value in _metadata_dict(profile, "hardware_registers").items():
        value = str(raw_value)
        lowered_key = register.lower()
        lowered_value = value.lower()
        if any(token in lowered_key for token in ("bootloader", "abl", "xbl", "sboot")):
            version_scores[value] = version_scores.get(value, 0.0) + 1.0
            _record_signal(evidence, "hardware_register", register, value, 1.0, "hardware register bootloader heuristic matched")
        if any(token in lowered_key for token in ("lock", "device_state", "oem_lock", "flash_locked")):
            if lowered_value in {"1", "true", "locked"}:
                lock_scores["locked"] = lock_scores.get("locked", 0.0) + 1.0
                _record_signal(evidence, "hardware_register", register, "locked", 1.0, "hardware register reports locked state")
            elif lowered_value in {"0", "false", "unlocked"}:
                lock_scores["unlocked"] = lock_scores.get("unlocked", 0.0) + 1.0
                _record_signal(evidence, "hardware_register", register, "unlocked", 1.0, "hardware register reports unlocked state")
        if any(token in lowered_key for token in ("vbmeta", "verified_boot", "avb")):
            for state in ("green", "yellow", "orange", "red"):
                if state in lowered_value:
                    verified_scores[state] = verified_scores.get(state, 0.0) + 1.0
                    _record_signal(evidence, "hardware_register", register, state, 1.0, "hardware register reports verified boot state")
                    break

    bootloader_version = _pick_state(version_scores, unknown="unknown")
    if bootloader_version == "unknown":
        bootloader_version = None
    lock_state = _pick_state(lock_scores, unknown="unknown", mixed="mixed")
    verified_state = _pick_state(verified_scores, unknown="unknown", mixed="mixed")

    active_slot = None
    inactive_slot = None
    slots = _metadata_dict(profile, "slots")
    if slots:
        for slot_name, slot_payload in slots.items():
            if isinstance(slot_payload, dict) and bool(slot_payload.get("active")):
                active_slot = str(slot_name)
        if active_slot is None:
            active_slot = _slot_suffix_from_sources(profile)
        if active_slot in {"a", "b"}:
            inactive_slot = "b" if active_slot == "a" else "a"
    else:
        active_slot = _slot_suffix_from_sources(profile)
        if active_slot in {"a", "b"}:
            inactive_slot = "b" if active_slot == "a" else "a"

    if lock_state == "locked" and verified_state == "green":
        security_state = "verified"
    elif lock_state == "mixed" or verified_state == "mixed":
        security_state = "inconsistent"
        heuristics.append("Conflicting security-state evidence detected across logs, cmdline, or registers.")
    elif lock_state == "unlocked" or verified_state in {"yellow", "orange", "red"}:
        security_state = "reduced_assurance"
    else:
        security_state = "unknown"

    if bootloader_version:
        heuristics.append(f"Bootloader version fingerprint resolved to {bootloader_version}.")
    else:
        heuristics.append("Bootloader version could not be resolved from supplied metadata.")
    if active_slot:
        heuristics.append(f"Active slot inferred as {active_slot}.")
    if lock_state != "unknown":
        heuristics.append(f"Device lock state inferred as {lock_state}.")
    if verified_state != "unknown":
        heuristics.append(f"Verified boot state inferred as {verified_state}.")

    return BootEnvironmentFingerprint(
        bootloader_version=bootloader_version,
        device_lock_state=lock_state,
        verified_boot_state=verified_state,
        security_state=security_state,
        active_slot=active_slot,
        inactive_slot=inactive_slot,
        evidence=evidence,
        heuristics=heuristics,
    )


def verify_ab_partitions(profile: TargetProfile) -> ABPartitionVerification:
    slots = _metadata_dict(profile, "slots")
    slot_summaries: list[SlotPartitionSummary] = []
    issues: list[SlotVerificationIssue] = []
    active_slot = None

    for slot_name in sorted(slots):
        slot_payload = slots.get(slot_name)
        if not isinstance(slot_payload, dict):
            continue
        if bool(slot_payload.get("active")):
            active_slot = str(slot_name)
        partitions = slot_payload.get("partitions")
        slot_summaries.append(
            SlotPartitionSummary(
                slot=str(slot_name),
                active=bool(slot_payload.get("active")),
                bootloader_version=_score_slot(slot_payload, "bootloader_version"),
                rollback_index=int(slot_payload["rollback_index"]) if str(slot_payload.get("rollback_index", "")).isdigit() else None,
                partitions=partitions if isinstance(partitions, dict) else {},
            )
        )

    if active_slot is None:
        fingerprint = fingerprint_boot_environment(profile)
        active_slot = fingerprint.active_slot
    inactive_slot = None
    if active_slot in {"a", "b"}:
        inactive_slot = "b" if active_slot == "a" else "a"

    by_slot = {item.slot: item for item in slot_summaries}
    active_summary = by_slot.get(active_slot or "")
    inactive_summary = by_slot.get(inactive_slot or "")

    if len(slot_summaries) < 2:
        issues.append(
            SlotVerificationIssue(
                slot=active_slot or "unknown",
                severity="medium",
                issue="missing_dual_slot_view",
                rationale="Enhanced A/B verification could not inspect both active and inactive slots from the supplied metadata.",
            )
        )
        return ABPartitionVerification(
            active_slot=active_slot,
            inactive_slot=inactive_slot,
            slot_summaries=slot_summaries,
            issues=issues,
        )

    if active_summary and inactive_summary:
        if active_summary.bootloader_version and inactive_summary.bootloader_version and active_summary.bootloader_version != inactive_summary.bootloader_version:
            issues.append(
                SlotVerificationIssue(
                    slot=inactive_summary.slot,
                    counterpart_slot=active_summary.slot,
                    severity="medium",
                    issue="bootloader_version_mismatch",
                    rationale=f"Inactive slot bootloader version {inactive_summary.bootloader_version} diverges from active slot {active_summary.bootloader_version}.",
                )
            )
        if active_summary.rollback_index is not None and inactive_summary.rollback_index is not None and inactive_summary.rollback_index < active_summary.rollback_index:
            issues.append(
                SlotVerificationIssue(
                    slot=inactive_summary.slot,
                    counterpart_slot=active_summary.slot,
                    severity="high",
                    issue="rollback_index_regression",
                    rationale=f"Inactive slot rollback index {inactive_summary.rollback_index} is lower than active slot {active_summary.rollback_index}, which can mask rollback exposure.",
                )
            )

        partition_names = sorted(set(active_summary.partitions) | set(inactive_summary.partitions))
        for partition in partition_names:
            left = active_summary.partitions.get(partition)
            right = inactive_summary.partitions.get(partition)
            if left is None or right is None:
                issues.append(
                    SlotVerificationIssue(
                        slot=inactive_summary.slot if right is None else active_summary.slot,
                        counterpart_slot=active_summary.slot if right is None else inactive_summary.slot,
                        partition=partition,
                        severity="high" if partition in {"vbmeta", "recovery"} else "medium",
                        issue="partition_missing_in_slot",
                        rationale=f"{partition} is not present in both slots, preventing symmetric verification of active and inactive partitions.",
                    )
                )
                continue
            left_sha = _score_slot(left if isinstance(left, dict) else {}, "sha256")
            right_sha = _score_slot(right if isinstance(right, dict) else {}, "sha256")
            if partition in {"vbmeta", "recovery"} and left_sha and right_sha and left_sha != right_sha:
                issues.append(
                    SlotVerificationIssue(
                        slot=inactive_summary.slot,
                        counterpart_slot=active_summary.slot,
                        partition=partition,
                        severity="medium",
                        issue="cross_slot_partition_mismatch",
                        rationale=f"{partition} differs between active and inactive slots; inspect for rollback residue or corrupted recovery state.",
                    )
                )
            if isinstance(left, dict) and left.get("corruption_flag"):
                issues.append(
                    SlotVerificationIssue(
                        slot=active_summary.slot,
                        counterpart_slot=inactive_summary.slot,
                        partition=partition,
                        severity="high",
                        issue="corruption_flagged",
                        rationale=f"{partition} in slot {active_summary.slot} is explicitly marked as corrupted in the supplied metadata.",
                    )
                )
            if isinstance(right, dict) and right.get("corruption_flag"):
                issues.append(
                    SlotVerificationIssue(
                        slot=inactive_summary.slot,
                        counterpart_slot=active_summary.slot,
                        partition=partition,
                        severity="high",
                        issue="corruption_flagged",
                        rationale=f"{partition} in slot {inactive_summary.slot} is explicitly marked as corrupted in the supplied metadata.",
                    )
                )

    return ABPartitionVerification(
        active_slot=active_slot,
        inactive_slot=inactive_slot,
        slot_summaries=slot_summaries,
        issues=issues,
    )


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
    fingerprint = fingerprint_boot_environment(profile)
    ab_verification = verify_ab_partitions(profile)
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
        "fingerprint": fingerprint.model_dump(mode="json"),
        "ab_verification": ab_verification.model_dump(mode="json"),
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
