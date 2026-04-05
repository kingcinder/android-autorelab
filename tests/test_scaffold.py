from __future__ import annotations

from pathlib import Path

from arelab.basement import prepare_basement
from arelab.bootchain import map_boot_chain
from arelab.disclosure import build_disclosure_manifest, build_disclosure_report
from arelab.exploit_refs import load_reference_catalog
from arelab.intake import build_intake_session
from arelab.targets import (
    fingerprint_boot_environment,
    load_target_profile_by_id,
    load_target_profiles,
    normalize_target_profile,
    rank_targets,
    verify_ab_partitions,
)


def _target_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "targets"


def test_target_profiles_normalize_and_rank_in_expected_order() -> None:
    profiles = load_target_profiles([], _target_dir())
    ranking = rank_targets(profiles)
    samsung = load_target_profile_by_id("samsung-a54-synthetic-001", [], _target_dir())

    assert [item.target_id for item in ranking] == [
        "samsung-a54-synthetic-001",
        "google-pixel7-synthetic-001",
        "motorola-gpower-synthetic-001",
    ]
    normalized = normalize_target_profile(samsung)
    assert normalized["canonical_keys"]["device_key"] == "samsung-a54"
    assert normalized["canonical_keys"]["build_key"] == "samsung-a546bxxs8xyz"
    assert normalized["artifact_count"] >= 2
    assert normalized["fingerprint"]["bootloader_version"] == "A546BXXS8XYZ"
    assert normalized["fingerprint"]["device_lock_state"] == "locked"
    assert normalized["fingerprint"]["verified_boot_state"] == "green"
    assert normalized["fingerprint"]["active_slot"] == "a"
    issues = {(item["issue"], item.get("partition")) for item in normalized["ab_verification"]["issues"]}
    assert ("bootloader_version_mismatch", None) in issues
    assert ("rollback_index_regression", None) in issues
    assert ("cross_slot_partition_mismatch", "vbmeta") in issues
    assert ("cross_slot_partition_mismatch", "recovery") in issues
    assert ("corruption_flagged", "recovery") in issues


def test_dynamic_fingerprinting_and_ab_verification_cover_clean_and_risky_profiles() -> None:
    samsung = load_target_profile_by_id("samsung-a54-synthetic-001", [], _target_dir())
    motorola = load_target_profile_by_id("motorola-gpower-synthetic-001", [], _target_dir())
    pixel = load_target_profile_by_id("google-pixel7-synthetic-001", [], _target_dir())

    samsung_fingerprint = fingerprint_boot_environment(samsung)
    motorola_fingerprint = fingerprint_boot_environment(motorola)
    pixel_ab = verify_ab_partitions(pixel)
    motorola_ab = verify_ab_partitions(motorola)

    assert samsung_fingerprint.security_state == "verified"
    assert samsung_fingerprint.inactive_slot == "b"
    assert samsung_fingerprint.evidence
    assert all(signal.value != "version" for signal in samsung_fingerprint.evidence if signal.key == "bootloader_version")
    assert motorola_fingerprint.device_lock_state == "unlocked"
    assert motorola_fingerprint.verified_boot_state == "orange"
    assert motorola_fingerprint.security_state == "reduced_assurance"
    assert {issue.issue for issue in pixel_ab.issues} == set()
    assert {issue.issue for issue in motorola_ab.issues} == {"missing_dual_slot_view"}


def test_historical_reference_catalog_is_analysis_only_and_matches_android_profiles() -> None:
    samsung = load_target_profile_by_id("samsung-a54-synthetic-001", [], _target_dir())
    catalog = load_reference_catalog()
    chain_map = map_boot_chain(samsung)

    assert catalog
    assert all(item.analysis_only for item in catalog)
    assert chain_map.operational_report is not None
    assert chain_map.operational_report.reference_matches
    assert all(item.analysis_only for item in chain_map.operational_report.reference_matches)
    match_ids = {item.id for item in chain_map.operational_report.reference_matches}
    assert "android-security-bulletins" in match_ids
    assert "magisk-boot-patching" in match_ids
    assert any(
        recommendation.id.startswith("review-reference-")
        for recommendation in chain_map.operational_report.validation_recommendations
    )


def test_bootchain_lookup_uses_yaml_target_id_and_exposures_are_valid(tmp_path: Path) -> None:
    alias_path = tmp_path / "alias.yaml"
    alias_path.write_text((_target_dir() / "samsung_a54.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    profile = load_target_profile_by_id("samsung-a54-synthetic-001", [alias_path])
    chain_map = map_boot_chain(profile)

    assert profile.target_id == "samsung-a54-synthetic-001"
    assert chain_map.target_id == "samsung-a54-synthetic-001"
    assert chain_map.fingerprint is not None
    assert chain_map.fingerprint.bootloader_version == "A546BXXS8XYZ"
    assert chain_map.ab_verification is not None
    assert chain_map.ab_verification.active_slot == "a"
    assert chain_map.operational_report is not None
    assert chain_map.operational_report.memory_regions
    assert chain_map.operational_report.timing_analysis
    assert chain_map.operational_report.correlations
    assert any("rollback exposure" in item.lower() for item in chain_map.operational_report.anomalies)
    assert any(item.id == "validate-rollback-metadata" for item in chain_map.operational_report.validation_recommendations)
    assert any(item.id == "magisk-boot-patching" for item in chain_map.operational_report.reference_matches)
    assert any(exposure.trust_boundary == "signed_to_signed" for exposure in chain_map.exposures)
    assert any(exposure.component == "slot_b" and exposure.exposure == "rollback_index_regression" for exposure in chain_map.exposures)
    assert chain_map.exposures


def test_disclosure_and_basement_outputs_are_workflow_scoped(tmp_path: Path) -> None:
    profile = load_target_profile_by_id("google-pixel7-synthetic-001", [], _target_dir())
    chain_map = map_boot_chain(profile)
    manifest = build_disclosure_manifest(profile, chain_map)
    report = build_disclosure_report(profile, chain_map, manifest)
    session = build_intake_session(
        tmp_path,
        source_type="reference_file_set",
        reference_paths="references/pixel7/reference-metadata.json",
        acquisition_notes="normalized metadata bundles",
    )

    index = prepare_basement(
        tmp_path / "runs" / "agency" / "case-001",
        "agency",
        session,
        target_profile=profile,
        bootchain_map=chain_map,
        disclosure_manifest=manifest,
        disclosure_report=report,
    )

    assert isinstance(manifest.generated_at, str)
    assert "Disclosure Scaffold: google-pixel7-synthetic-001" in report
    assert "Historical References" in report
    assert Path(index["target_profile"]).exists()
    assert Path(index["bootchain_map"]).exists()
    assert Path(index["operational_report"]).exists()
    assert Path(index["disclosure_manifest"]).exists()
    assert Path(index["disclosure_report"]).exists()
    assert "runs" in index["bootchain_map"]
    assert "agency" in index["bootchain_map"]
    assert "agency" in index["operational_report"]
