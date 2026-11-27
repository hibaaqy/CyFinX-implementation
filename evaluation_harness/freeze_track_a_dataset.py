#!/usr/bin/env python3
"""Freeze and hash the Track A snapshot dataset."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", default="evaluation_harness")
    parser.add_argument("--output", default="track_a_dataset_manifest.json")
    args = parser.parse_args()

    harness = Path(args.harness)
    snapshot_folder = harness / "snapshots"
    ground_truth = harness / "ground_truth" / "Ground_Truth.csv"

    snapshot_files = sorted(snapshot_folder.glob("*.json"))
    manifest = {
        "benchmark": "CyFinX Track A",
        "dataset_version": "CyFinX_V3_2500_210_cases",
        "snapshot_count": len(snapshot_files),
        "snapshot_sha256": {
            path.name: sha256(path)
            for path in snapshot_files
        },
        "ground_truth_sha256": sha256(ground_truth),
        "ground_truth_excluded_from_model_inputs": True,
    }
    output = harness / args.output
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({
        "snapshot_count": len(snapshot_files),
        "ground_truth_sha256": manifest["ground_truth_sha256"],
        "manifest": str(output),
    }, indent=2))


if __name__ == "__main__":
    main()
