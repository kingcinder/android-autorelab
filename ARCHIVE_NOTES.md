# Archive Notes

This copy is intended for GitHub archiving and maintenance.

## Portable defaults

- The repo no longer relies on `/home/oem/android-autorelab`.
- Workflow service files are installed from templates and rewritten to the current repo root by `scripts/install_services.sh` and `scripts/install_workflow_services.sh`.
- Router launchers now prefer `ARELAB_LLAMA_SERVER`, then `llama-server` on `PATH`.
- Workflow model directories resolve from `ARELAB_MODELS_DIR` or the repo-local `models/` directory.

## Included proof artifacts

- `proof-runs/default/`
- `proof-runs/agency/`
- `proof-runs/legion/`

These are the latest successful proof reports copied from the working project for archival reference.
