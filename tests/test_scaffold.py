from __future__ import annotations

from pathlib import Path

from arelab.basement import prepare_basement
from arelab.bootchain import map_boot_chain
from arelab.disclosure import build_disclosure_manifest, build_disclosure_report
from arelab.intake import build_intake_session
from arelab.targets import (
    load_target_profile_by_id,
    load_target_profiles,
    normalize_target_profile,
    rank_targets,
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


def test_bootchain_lookup_uses_yaml_target_id_and_exposures_are_valid(tmp_path: Path) -> None:
    alias_path = tmp_path / "alias.yaml"
    alias_path.write_text((_target_dir() / "samsung_a54.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    profile = load_target_profile_by_id("samsung-a54-synthetic-001", [alias_path])
    chain_map = map_boot_chain(profile)

    assert profile.target_id == "samsung-a54-synthetic-001"
    assert chain_map.target_id == "samsung-a54-synthetic-001"
    assert any(exposure.trust_boundary == "signed_to_signed" for exposure in chain_map.exposures)
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
    assert Path(index["target_profile"]).exists()
    assert Path(index["bootchain_map"]).exists()
    assert Path(index["disclosure_manifest"]).exists()
    assert Path(index["disclosure_report"]).exists()
    assert "runs" in index["bootchain_map"]
    assert "agency" in index["bootchain_map"]
