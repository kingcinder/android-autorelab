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
