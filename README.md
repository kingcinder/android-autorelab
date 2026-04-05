# android-autorelab

`android-autorelab` is a local-first Android reverse-engineering lab suite for authorized, defensive analysis. It normalizes intake context, preserves provenance, runs workflow-scoped analysis, and emits evidence-backed Security Weakness Assessment Points (SWAPs) and disclosure scaffolds rather than exploit guidance.

## Current shape

- The first served screen is a shared intake routing splash at `/`, not the run ledger.
- Intake remains workflow-neutral until the user explicitly binds the session to `The Agency` or `The Legion`.
- Workflow outputs stay separated under `runs/agency/...` and `runs/legion/...`.
- `The Basement` is a shared subordinate utility layer, but its outputs remain scoped under `runs/<workflow>/basement/...`.
- The run ledger remains available at `/runs`.

## Core concepts

### Shared intake

The startup flow supports three intake modes before workflow selection:

- Acquire from physical target device
- Load saved project
- Load reference file or reference file set

Each intake session records:

- what was provided
- what was inferred
- what remains unknown
- provenance and acquisition notes

Reference wording explicitly supports cases such as downloaded firmware files, vendor firmware packages, extracted images, prior evidence bundles, and normalized metadata bundles.

### The Agency and The Legion

Two primary workflows exist and remain exclusive:

- `The Agency`: serial deep-audit workflow, router port `18081`, `models_max: 1`
- `The Legion`: parallel swarm workflow, router port `18082`, `models_max: 3`

Both workflows enforce separation through workflow-scoped run roots, locks, and router startup rules.

### The Basement

`The Basement` is not a third workflow. It is a shared subordinate routine layer used for:

- intake support
- normalization support
- evidence organization
- mapping support
- validation support
- reproducibility scaffolding
- disclosure preparation support

Outputs stay under the invoking workflow:

- `runs/agency/<run_id>/basement/...`
- `runs/legion/<run_id>/basement/...`

## Repo layout

```text
config/
  targets/
  workflows/
docs/
scripts/
src/arelab/
templates/
runs/
  agency/
  legion/
```

Useful docs:

- [docs/target-intake.md](docs/target-intake.md)
- [docs/boot-chain-research.md](docs/boot-chain-research.md)

## Installation

### Python environment

The repo expects Python 3.12+ and creates a local `.venv`:

```bash
./scripts/install.sh
```

The installer sets up the editable package and verifies the core Python stack. It does not commit local machine configuration.

### External tools

For full shell verification, the host toolchain should provide:

- `binwalk`
- `file`
- `strings`
- `gcc`
- Ghidra headless (`analyzeHeadless`)
- a local `llama-server` backend with access to the configured models

Tool detection prefers:

1. explicit local overrides
2. discovered executables on `PATH`
3. adjacent Ghidra support paths when a Ghidra launcher is discovered

If host-specific overrides are needed, use a local untracked `config/local-overrides.yaml`.

## Quick start

### Serve the UI

```bash
arelab --repo-root . serve --host 127.0.0.1 --port 8765
```

Then open:

- `/` for the shared intake splash
- `/runs` for the run ledger

### CLI entrypoints

```bash
arelab run --input /path/to/artifact --profile fast
arelab demo --profile fast
arelab status <run_id>
arelab report <run_id> --format md
agencyctl run --input /path/to/artifact --profile deep
legionctl run --input /path/to/artifact --profile overnight
```

### Target scaffold commands

```bash
intake_target --config-dir config/targets --target-id samsung-a54-synthetic-001 --output target-intake.json
score_targets --config-dir config/targets --output target-scores.json
map_bootchain --config-dir config/targets --target-id google-pixel7-synthetic-001 --output bootchain.json
```

These commands restore the boot-chain scaffold for:

- target normalization
- defensive target prioritization
- boot-stage and trust-boundary mapping
- disclosure/evidence scaffolding

## Verification

### Shared and workflow-specific

```bash
./scripts/verify_shared.sh
./scripts/verify_agency.sh
./scripts/verify_legion.sh
./scripts/verify.sh
```

`verify.sh` is the top-level shell path. It runs the shared verifier, the Agency verifier, and the Legion verifier end to end.

The workflow verifiers prove:

- router startup and readiness
- workflow exclusivity
- model load and unload behavior
- proof-run report generation
- workflow-scoped output separation

### Windows notes

The repo has been verified locally on Windows with:

- PowerShell
- Git Bash for shell scripts
- workflow-scoped temp/runtime state
- detached router launch via Python rather than shell job control
- process-tree cleanup and liveness checks via `psutil`

Windows-safe repo paths are handled in the shell helpers and Python router/lock tooling. Avoid committing host-local overrides.

## Configuration

Tracked config lives under:

- `config/workflows/agency.yaml`
- `config/workflows/legion.yaml`
- `config/models.yaml`
- `config/tools.yaml`
- `config/policies.yaml`

Common local override use cases:

- router model directory
- selected verification model
- `llama-server` binary path
- `analyzeHeadless` path
- tool overrides such as `binwalk`, `gcc`, `strings`, `nm`, or `objdump`

Local overrides belong in `config/local-overrides.yaml`, which is intentionally kept out of tracked content.

## Safety stance

- authorized analysis only
- no exploit generation
- no flashing, rooting, or bypass workflows
- read-only defaults
- provenance, evidence handling, and remediation-oriented reporting

## Synthetic target examples

The restored scaffold includes example target profiles such as:

- `samsung-a54-synthetic-001`
- `motorola-gpower-synthetic-001`
- `google-pixel7-synthetic-001`

These are for defensive research scaffolding and verification only.
