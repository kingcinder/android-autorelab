# Boot-Chain Research Scaffold

This repo includes a controlled boot-chain scaffold for authorized Android security research.

Included capabilities:

- target profile loading and normalization
- target prioritization scoring
- boot-stage and trust-boundary mapping
- disclosure-grade evidence manifest and report scaffolding

The scaffold is synthetic and metadata-oriented. It does not add exploit workflows, device compromise steps, or flashing guidance.

Windows-safe repo paths:

- `python scripts/intake_target.py --config-dir config/targets`
- `python scripts/score_targets.py --config-dir config/targets`
- `python scripts/map_bootchain.py --config-dir config/targets --target-id google-pixel7-synthetic-001`

When invoked from a workflow run, Basement output must stay under `runs/<workflow>/basement/`.
