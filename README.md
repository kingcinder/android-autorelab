# android-autorelab

`android-autorelab` is a local-first Android reverse-engineering lab suite for defensive, authorized analysis. It ingests firmware-related inputs, distills them into structured evidence, and emits ranked Security Weakness Assessment Points (SWAPs) with remediation intent instead of exploit guidance.

## What it does

- Accepts directories, archives, partition images, and binary artifacts.
- Preserves a run bundle under `runs/<timestamp>/` with logs, prompts, artifacts, and reports.
- Uses read-only analysis defaults and records every tool and model interaction.
- Produces `report.md` and `report.json` with evidence, reachability rationale, and fix-oriented recommendations.
- Includes a reproducible proof run that builds a demo binary with intentionally unsafe patterns and verifies the pipeline can flag them.

## Quick start

```bash
cd android-autorelab
./scripts/install.sh
./scripts/verify.sh
```

## CLI

```bash
arelab run --input /path/to/artifact --profile overnight
arelab demo --profile overnight
arelab status <run_id>
arelab report <run_id> --format md
arelab serve --host 127.0.0.1 --port 8765
agencyctl run --input /path/to/artifact --profile deep
legionctl run --input /path/to/artifact --profile overnight
```

## Workflows

Two exclusive workflow states are now modeled inside the same repo:

- `The Agency`: serial deep pipeline with router `models_max: 1`, explicit stage order `planner -> decompile_refine -> primary auditor -> arbiter`, dedicated config in `config/workflows/agency.yaml`, launcher scripts in `scripts/start_agency.sh` and `scripts/verify_agency.sh`, and the `agency.service` user unit in `services/agency.service`.
- `The Legion`: lane-based parallel workflow with router `models_max: 3`, dedicated config in `config/workflows/legion.yaml`, launcher scripts in `scripts/start_legion.sh` and `scripts/verify_legion.sh`, and the `legion.service` user unit in `services/legion.service`.

Both workflows are guarded by the runtime lock in `src/arelab/locks.py` and user-level `systemd` unit conflicts so they do not co-run.

Useful commands:

```bash
./scripts/start_agency.sh
./scripts/stop_agency.sh
./scripts/start_legion.sh
./scripts/stop_legion.sh
./scripts/verify_agency.sh
./scripts/verify_legion.sh
```

Agency-specific notes:

- `agencyctl` is the serial workflow entrypoint and keeps the router to a single loaded model while stages rotate.
- `scripts/verify_agency.sh` proves two things: `agency.service` displaces `legion.service` when user `systemd` is available, and the Agency proof run completes with only one loaded model at a time from the configured serial stage list.

### Legion operations

`The Legion` is the parallel swarm state described in the workflow spec:

- Router mode runs on `127.0.0.1:18082` with `models_max: 3`, `ctx_size: 4096`, `autoload: false`, and explicit `/models/load` + `/models/unload` verification from `scripts/workflow_verify.py`.
- `services/legion.service` hard-conflicts with `agency.service`, starts only after an explicit Agency stop pre-step, and uses the foreground Legion launcher for user-service installs.
- `scripts/start_legion.sh` clears stale workflow lock state, stops any Agency launcher first, and then starts the Legion router. `scripts/stop_legion.sh` clears only Legion-owned runtime state.
- `scripts/verify_legion.sh` proves exclusivity, checks `/models`, loads and unloads the configured Legion verification models, records RSS snapshots for the router process tree, and then runs a Legion demo proof report under `runs/legion/`.

## Model gateway

The suite reads:

- `ARELAB_OPENAI_BASE_URL` defaulting to `http://127.0.0.1:10000/v1`
- `ARELAB_OPENAI_API_KEY` defaulting to `none`

If the default endpoint is unavailable, the gateway also probes `http://127.0.0.1:8000/v1`, which matches the current local llama.cpp stack on this workstation.

Logical model roles can be pinned in `config/models.yaml`.
Workflow-specific routing, ports, and mode policies live under `config/workflows/`.

## Tooling notes

- `binwalk`, `simg2img`, and Ghidra headless are auto-detected when installed.
- `lpunpack`, `unpack_bootimg.py`, and `avbtool` are exposed through repo-local wrappers so install/verify can standardize usage even before optional system tools are added.
- `angr` is optional at import time but installed by `scripts/install.sh` for CFG extraction.

## Safety stance

- No exploit generation, payloads, or compromise playbooks.
- No flashing, unlocking, rooting, or AVB bypass workflows.
- Read-only by default; privileged operations remain explicit and logged.
- Reports provide reproducible evidence and remediation intent only.
