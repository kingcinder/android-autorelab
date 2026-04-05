from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolExecution(BaseModel):
    label: str
    command: list[str]
    cwd: str
    started_at: str
    finished_at: str
    exit_code: int
    stdout_path: str
    stderr_path: str
    log_path: str


class ArtifactNode(BaseModel):
    path: str
    kind: str
    mime: str | None = None
    sha256: str | None = None
    size: int | None = None
    source: str | None = None
    derived_from: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactManifest(BaseModel):
    input_path: str
    created_at: str
    nodes: list[ArtifactNode]


class FunctionFact(BaseModel):
    name: str
    address: str
    pseudocode: str | None = None
    assembly_excerpt: str | None = None
    xref_count: int | None = None
    cfg_nodes: int | None = None
    cfg_edges: int | None = None
    notes: list[str] = Field(default_factory=list)


class BinaryAnalysis(BaseModel):
    binary: str
    sha256: str
    file_output: str
    imports: list[str] = Field(default_factory=list)
    strings: list[str] = Field(default_factory=list)
    functions: list[FunctionFact] = Field(default_factory=list)
    cfg_summary: dict[str, Any] = Field(default_factory=dict)
    ghidra_summary: dict[str, Any] = Field(default_factory=dict)
    heuristics: list[dict[str, Any]] = Field(default_factory=list)


class SwapEvidence(BaseModel):
    binary: str
    function: str
    address: str
    decompile_excerpt: str
    cfg_summary: str


class SwapCandidate(BaseModel):
    id: str = ""
    title: str
    class_name: str = Field(alias="class")
    confidence: float
    impact: Literal["low", "med", "high", "critical"]
    reachability: str
    evidence: SwapEvidence
    remediation_intent: str
    verification_tests: str
    sources: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class SwapReport(BaseModel):
    run_id: str
    generated_at: str
    summary: dict[str, Any]
    swap_candidates: list[SwapCandidate]
    artifacts: ArtifactManifest
    analyses: list[BinaryAnalysis]


class RunMetadata(BaseModel):
    run_id: str
    workflow: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    updated_at: str
    input_path: str
    output_root: str
    profile: str
    stage: str
    error: str | None = None
    report_path: str | None = None
    basement_path: str | None = None
    intake_session_id: str | None = None
    source_type: str | None = None


class IntakeReference(BaseModel):
    raw_value: str
    resolved_path: str
    exists: bool
    inferred_kind: str


class IntakeSessionContext(BaseModel):
    session_id: str
    created_at: str
    source_type: Literal["physical_target_device", "saved_project", "reference_file_set"]
    provided: dict[str, Any] = Field(default_factory=dict)
    inferred: dict[str, Any] = Field(default_factory=dict)
    unknown: list[str] = Field(default_factory=list)
    provenance_notes: list[str] = Field(default_factory=list)
    references: list[IntakeReference] = Field(default_factory=list)
    canonical_keys: dict[str, str] = Field(default_factory=dict)


class TargetArtifact(BaseModel):
    name: str
    kind: str
    provenance: str
    path_hint: str | None = None
    completeness: float = 0.0
    notes: list[str] = Field(default_factory=list)


class BootComponent(BaseModel):
    name: str
    stage: str
    signed: bool = True
    verifies: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TargetProfile(BaseModel):
    target_id: str
    vendor: str
    family: str
    model: str
    build_id: str
    bootchain_depth: int
    artifact_completeness: float
    recency_rank: int
    disclosure_value: int
    vendor_weight: float
    authorized_scope: str
    acquisition_notes: list[str] = Field(default_factory=list)
    artifacts: list[TargetArtifact] = Field(default_factory=list)
    boot_components: list[BootComponent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TargetScore(BaseModel):
    target_id: str
    score: float
    rationale: dict[str, float] = Field(default_factory=dict)


class FingerprintSignal(BaseModel):
    source: Literal["boot_log", "kernel_cmdline", "hardware_register"]
    key: str
    value: str
    confidence: float
    rationale: str


class BootEnvironmentFingerprint(BaseModel):
    bootloader_version: str | None = None
    device_lock_state: Literal["locked", "unlocked", "mixed", "unknown"] = "unknown"
    verified_boot_state: Literal["green", "yellow", "orange", "red", "mixed", "unknown"] = "unknown"
    security_state: Literal["verified", "reduced_assurance", "inconsistent", "unknown"] = "unknown"
    active_slot: str | None = None
    inactive_slot: str | None = None
    evidence: list[FingerprintSignal] = Field(default_factory=list)
    heuristics: list[str] = Field(default_factory=list)


class SlotPartitionSummary(BaseModel):
    slot: str
    active: bool = False
    bootloader_version: str | None = None
    rollback_index: int | None = None
    partitions: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SlotVerificationIssue(BaseModel):
    slot: str
    counterpart_slot: str | None = None
    partition: str | None = None
    severity: Literal["low", "medium", "high"]
    issue: str
    rationale: str


class ABPartitionVerification(BaseModel):
    active_slot: str | None = None
    inactive_slot: str | None = None
    slot_summaries: list[SlotPartitionSummary] = Field(default_factory=list)
    issues: list[SlotVerificationIssue] = Field(default_factory=list)


class MemoryHexDump(BaseModel):
    region: str
    address: str | None = None
    source: str = "metadata"
    hexdump: str
    notes: list[str] = Field(default_factory=list)


class BootStageTiming(BaseModel):
    stage: str
    started_ms: int
    ended_ms: int | None = None
    duration_ms: int | None = None
    source: str = "metadata"


class EventCorrelation(BaseModel):
    software_event: str
    hardware_signal: str
    software_timestamp_ms: int
    hardware_timestamp_ms: int
    delta_ms: int
    stage: str | None = None
    interpretation: str


class ValidationRecommendation(BaseModel):
    id: str
    title: str
    rationale: str
    applicability: str
    steps: list[str] = Field(default_factory=list)


class ReferenceLink(BaseModel):
    label: str
    url: str


class ExploitReference(BaseModel):
    id: str
    title: str
    collection_kind: str
    summary: str
    analysis_only: bool = True
    cves: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    vendor_hints: list[str] = Field(default_factory=list)
    stage_hints: list[str] = Field(default_factory=list)
    issue_hints: list[str] = Field(default_factory=list)
    lock_state_hints: list[str] = Field(default_factory=list)
    verified_boot_state_hints: list[str] = Field(default_factory=list)
    keyword_hints: list[str] = Field(default_factory=list)
    validation_focus: list[str] = Field(default_factory=list)
    references: list[ReferenceLink] = Field(default_factory=list)


class ExploitReferenceMatch(BaseModel):
    id: str
    title: str
    collection_kind: str
    classification: Literal["applicable", "possibly_applicable"]
    score: float
    rationale: list[str] = Field(default_factory=list)
    analysis_only: bool = True
    cves: list[str] = Field(default_factory=list)
    validation_focus: list[str] = Field(default_factory=list)
    references: list[ReferenceLink] = Field(default_factory=list)


class BootOperationalReport(BaseModel):
    target_id: str
    generated_at: str
    memory_regions: list[MemoryHexDump] = Field(default_factory=list)
    timing_analysis: list[BootStageTiming] = Field(default_factory=list)
    correlations: list[EventCorrelation] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    validation_recommendations: list[ValidationRecommendation] = Field(default_factory=list)
    reference_matches: list[ExploitReferenceMatch] = Field(default_factory=list)


class BootChainExposure(BaseModel):
    component: str
    stage: str
    trust_boundary: Literal[
        "signed_to_signed",
        "signed_to_unsigned",
        "unsigned_to_signed",
        "unsigned_to_unsigned",
    ]
    exposure: str
    evidence: list[str] = Field(default_factory=list)
    remediation_focus: str
    finding_scaffold: dict[str, str] = Field(default_factory=dict)


class BootChainMap(BaseModel):
    target_id: str
    created_at: str
    stage_map: dict[str, list[str]] = Field(default_factory=dict)
    trust_boundaries: list[dict[str, Any]] = Field(default_factory=list)
    fingerprint: BootEnvironmentFingerprint | None = None
    ab_verification: ABPartitionVerification | None = None
    operational_report: BootOperationalReport | None = None
    exposures: list[BootChainExposure] = Field(default_factory=list)
    finding_scaffolds: list[dict[str, str]] = Field(default_factory=list)


class DisclosureManifest(BaseModel):
    target_id: str
    generated_at: str
    chain_of_custody: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    exposures: list[dict[str, Any]] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
