# Private Track A dataset access

The Track A snapshots and ground-truth labels are private and are not included
in this repository. Authorized users must obtain the frozen dataset from the
project owner or dataset custodian through the approved private channel. Do not
copy it into a public repository, issue, pull request, or public artifact.

## Local layout

Place the authorized evaluation files beside `evaluation_runner.py`:

```text
evaluation_harness/
├── snapshots/
│   ├── CASE0000001.json
│   └── ... (all 210 frozen snapshots)
└── ground_truth/
    └── Ground_Truth.csv
```

Keep the supplied files unchanged. `track_a_dataset_manifest.json` contains
the expected SHA-256 digest for every snapshot and for `Ground_Truth.csv`.
Every runner invocation verifies the snapshot set and hashes before proceeding;
missing files, unexpected snapshots, and mismatches stop the run with a
preflight error. Do not regenerate or edit the manifest to silence a mismatch.

The runner reads ground truth only for offline validation of model responses.
It builds model prompts from the frozen snapshot, common task prompt, and task
schema; it does not add ground-truth labels, fraud types, scenario IDs, or
validation notes to those prompts.

The local `snapshots/` and `ground_truth/` directories are excluded by this
folder's `.gitignore`. Keep run outputs local as well; raw outputs contain
private case evidence.
