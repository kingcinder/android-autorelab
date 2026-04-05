from __future__ import annotations

from arelab.schemas import (
    ABPartitionVerification,
    BootEnvironmentFingerprint,
    BootOperationalReport,
    BootStageTiming,
    EventCorrelation,
    MemoryHexDump,
    TargetProfile,
    ValidationRecommendation,
)
from arelab.exploit_refs import build_reference_recommendations, match_reference_catalog
from arelab.util import truncate_text, utc_now


def _hexdump(value: str, width: int = 16) -> str:
    normalized = "".join(ch for ch in value if ch.lower() in "0123456789abcdef")
    if not normalized:
        return ""
    pairs = [normalized[index : index + 2] for index in range(0, len(normalized), 2)]
    lines: list[str] = []
    for offset in range(0, len(pairs), width):
        chunk = pairs[offset : offset + width]
        lines.append(f"{offset:08x}: {' '.join(chunk)}")
    return "\n".join(lines)


def _build_memory_regions(profile: TargetProfile) -> list[MemoryHexDump]:
    regions = profile.metadata.get("memory_regions")
    if not isinstance(regions, list):
        return []
    payload: list[MemoryHexDump] = []
    for item in regions:
        if not isinstance(item, dict):
            continue
        hexdump = _hexdump(str(item.get("bytes_hex", "")))
        if not hexdump:
            continue
        payload.append(
            MemoryHexDump(
                region=str(item.get("region", "unknown")),
                address=str(item["address"]) if item.get("address") is not None else None,
                source=str(item.get("source", "metadata")),
                hexdump=hexdump,
                notes=[str(note) for note in item.get("notes", []) if note is not None],
            )
        )
    return payload


def _build_timing_analysis(profile: TargetProfile) -> list[BootStageTiming]:
    timeline = profile.metadata.get("boot_timeline")
    if not isinstance(timeline, list):
        return []
    payload: list[BootStageTiming] = []
    for item in timeline:
        if not isinstance(item, dict) or item.get("stage") is None or item.get("started_ms") is None:
            continue
        started_ms = int(item["started_ms"])
        ended_ms = int(item["ended_ms"]) if item.get("ended_ms") is not None else None
        duration_ms = int(item["duration_ms"]) if item.get("duration_ms") is not None else None
        if duration_ms is None and ended_ms is not None:
            duration_ms = max(0, ended_ms - started_ms)
        payload.append(
            BootStageTiming(
                stage=str(item["stage"]),
                started_ms=started_ms,
                ended_ms=ended_ms,
                duration_ms=duration_ms,
                source=str(item.get("source", "metadata")),
            )
        )
    return payload


def _build_correlations(profile: TargetProfile) -> list[EventCorrelation]:
    software_events = profile.metadata.get("software_events")
    hardware_signals = profile.metadata.get("hardware_signals")
    if not isinstance(software_events, list) or not isinstance(hardware_signals, list):
        return []
    correlations: list[EventCorrelation] = []
    for event in software_events:
        if not isinstance(event, dict) or event.get("timestamp_ms") is None or event.get("event") is None:
            continue
        stage = str(event["stage"]) if event.get("stage") is not None else None
        candidates = [
            signal
            for signal in hardware_signals
            if isinstance(signal, dict)
            and signal.get("timestamp_ms") is not None
            and signal.get("signal") is not None
            and (stage is None or signal.get("stage") == stage)
        ]
        if not candidates:
            continue
        event_ts = int(event["timestamp_ms"])
        nearest = min(candidates, key=lambda signal: abs(int(signal["timestamp_ms"]) - event_ts))
        signal_ts = int(nearest["timestamp_ms"])
        delta = abs(signal_ts - event_ts)
        if delta > 150:
            continue
        correlations.append(
            EventCorrelation(
                software_event=str(event["event"]),
                hardware_signal=str(nearest["signal"]),
                software_timestamp_ms=event_ts,
                hardware_timestamp_ms=signal_ts,
                delta_ms=delta,
                stage=stage,
                interpretation=f"{event['event']} correlates with {nearest['signal']} at {delta} ms offset",
            )
        )
    return correlations


def _build_anomalies(
    fingerprint: BootEnvironmentFingerprint,
    ab_verification: ABPartitionVerification,
    timing_analysis: list[BootStageTiming],
    correlations: list[EventCorrelation],
) -> list[str]:
    anomalies: list[str] = []
    if fingerprint.security_state not in {"verified", "unknown"}:
        anomalies.append(
            f"Fingerprint indicates security_state={fingerprint.security_state}, lock_state={fingerprint.device_lock_state}, verified_boot_state={fingerprint.verified_boot_state}."
        )
    for item in timing_analysis:
        if item.duration_ms is not None and item.duration_ms > 400:
            anomalies.append(f"Boot stage {item.stage} exceeded 400 ms ({item.duration_ms} ms).")
    if timing_analysis and not correlations:
        anomalies.append("No software-to-hardware correlation was resolved from supplied timing data.")
    for issue in ab_verification.issues:
        anomalies.append(truncate_text(issue.rationale, 180))
    return anomalies


def _build_validation_recommendations(
    fingerprint: BootEnvironmentFingerprint,
    ab_verification: ABPartitionVerification,
) -> list[ValidationRecommendation]:
    recommendations: list[ValidationRecommendation] = []
    if fingerprint.security_state != "verified":
        recommendations.append(
            ValidationRecommendation(
                id="validate-security-state",
                title="Validate boot-state controls",
                rationale="The inferred boot security state is weaker than a locked green-path boot.",
                applicability=f"lock_state={fingerprint.device_lock_state}, verified_boot_state={fingerprint.verified_boot_state}",
                steps=[
                    "Capture synchronized boot logs, kernel cmdline, and register snapshots from the same boot.",
                    "Confirm OEM lock and AVB policy against trusted acquisition evidence.",
                    "Re-run fingerprinting after reacquiring evidence to distinguish stale data from live drift.",
                ],
            )
        )
    for issue in ab_verification.issues:
        if issue.issue == "rollback_index_regression":
            recommendations.append(
                ValidationRecommendation(
                    id="validate-rollback-metadata",
                    title="Audit rollback metadata across both slots",
                    rationale=issue.rationale,
                    applicability=f"slot={issue.slot}, counterpart={issue.counterpart_slot}",
                    steps=[
                        "Reacquire rollback metadata from both slots in the same session.",
                        "Compare active and inactive rollback indices against vendor expectations.",
                        "Preserve both slot views in the evidence bundle before further triage.",
                    ],
                )
            )
        elif issue.issue == "cross_slot_partition_mismatch":
            recommendations.append(
                ValidationRecommendation(
                    id=f"validate-cross-slot-{issue.partition or 'partition'}",
                    title="Review cross-slot partition mismatch",
                    rationale=issue.rationale,
                    applicability=f"partition={issue.partition}, slot={issue.slot}",
                    steps=[
                        "Re-hash the named partition from both active and inactive slots.",
                        "Confirm whether the mismatch is expected for the build or indicates stale or corrupted evidence.",
                        "Document both hashes and acquisition timestamps in the disclosure bundle.",
                    ],
                )
            )
        elif issue.issue == "missing_dual_slot_view":
            recommendations.append(
                ValidationRecommendation(
                    id="collect-inactive-slot-artifacts",
                    title="Collect the missing inactive-slot view",
                    rationale=issue.rationale,
                    applicability=f"active_slot={ab_verification.active_slot or 'unknown'}",
                    steps=[
                        "Acquire artifacts for the inactive slot before treating a single-slot result as complete.",
                        "Re-run A/B verification after both slots are available.",
                        "Preserve provenance notes describing why only one slot was initially visible.",
                    ],
                )
            )
        elif issue.issue == "corruption_flagged":
            recommendations.append(
                ValidationRecommendation(
                    id=f"reacquire-{issue.partition or 'partition'}",
                    title="Reacquire the flagged partition",
                    rationale=issue.rationale,
                    applicability=f"partition={issue.partition}, slot={issue.slot}",
                    steps=[
                        "Reacquire the partition image from the same target and compare hashes.",
                        "Correlate the partition anomaly with boot timing and hardware signal evidence.",
                        "Record whether corruption persists across repeat acquisition.",
                    ],
                )
            )
    return recommendations


def build_operational_report(
    profile: TargetProfile,
    fingerprint: BootEnvironmentFingerprint,
    ab_verification: ABPartitionVerification,
) -> BootOperationalReport:
    reference_matches = match_reference_catalog(profile, fingerprint, ab_verification)
    memory_regions = _build_memory_regions(profile)
    timing_analysis = _build_timing_analysis(profile)
    correlations = _build_correlations(profile)
    anomalies = _build_anomalies(fingerprint, ab_verification, timing_analysis, correlations)
    recommendations = _build_validation_recommendations(fingerprint, ab_verification)
    recommendations.extend(build_reference_recommendations(reference_matches))
    return BootOperationalReport(
        target_id=profile.target_id,
        generated_at=utc_now(),
        memory_regions=memory_regions,
        timing_analysis=timing_analysis,
        correlations=correlations,
        anomalies=anomalies,
        validation_recommendations=recommendations,
        reference_matches=reference_matches,
    )
