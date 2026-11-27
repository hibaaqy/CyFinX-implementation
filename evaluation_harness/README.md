# CyFinX Track A Evaluation Harness

This harness runs the frozen CyFinX Track A investigation tasks against a
configurable set of locally loaded Hugging Face models. It records response
validity and runtime measurements while keeping the private case snapshots and
ground-truth file outside Git.

## Workflow

1. Obtain the authorized private snapshots and ground truth as described in
   [DATASET_ACCESS.md](./DATASET_ACCESS.md).
2. Install Python dependencies and a CUDA-compatible PyTorch build.
3. Run the harness without `--execute` to validate inputs and inspect the run
   plan. This still requires the private dataset because integrity checks are
   mandatory.
4. Add `--execute` to load models and perform inference.
5. Review the local results and run metadata. Do not commit raw outputs or
   case-level results.

## Supported models

Model keys and Hugging Face IDs are defined in `model_registry.py`.

| Key | Hugging Face model ID | Loader |
| --- | --- | --- |
| `qwen3_5_4b` | `Qwen/Qwen3.5-4B` | multimodal |
| `qwen3_5_2b` | `Qwen/Qwen3.5-2B` | multimodal |
| `granite_3_3_2b` | `ibm-granite/granite-3.3-2b-instruct` | causal |
| `qwen3_1_7b` | `Qwen/Qwen3-1.7B` | causal |
| `phi4_mini` | `microsoft/Phi-4-mini-instruct` | causal |
| `ministral3_8b` | `mistralai/Ministral-3-8B-Instruct-2512-BF16` | multimodal |
| `gemma_4_e2b` | `google/gemma-4-E2B-it` | multimodal |

Ministral 3 8B uses the `Mistral3ForConditionalGeneration` architecture. The
model's Hugging Face configuration identifies it as `mistral3`; the
`AutoModelForImageTextToText` mapping in Transformers resolves that config to
the model class used by the harness's multimodal loader.

## Python, GPU, and dependencies

- Python 3.10 or newer is recommended.
- Model execution requires a CUDA-capable NVIDIA GPU and a PyTorch build
  compatible with its CUDA runtime. Memory needs depend on model, quantization,
  and prompt length; this harness does not prescribe a minimum VRAM value.
- The default quantization is 4-bit and uses `bitsandbytes`. An 8-bit run also
  needs `bitsandbytes`. Install a CUDA-enabled PyTorch build separately using
  the selector at <https://pytorch.org/get-started/locally/>; the right command
  depends on the target operating system and CUDA runtime.
- The Transformers constraint supports the Ministral 3 configuration mapping.
  Keep the Transformers version compatible with each model's current
  Hugging Face requirements.

From the repository root, install the listed Python packages with:

```powershell
python -m pip install -r evaluation_harness\requirements.txt
```

Then install the appropriate CUDA-enabled PyTorch build separately. Model
weights are downloaded by Transformers on first execution and remain in the
local Hugging Face cache; no model weights or credentials belong in this
repository.

## Dataset setup

The runner expects the frozen private dataset at `snapshots/` and
`ground_truth/Ground_Truth.csv`, beside `evaluation_runner.py`. Obtain it only
through the authorized private channel. The complete expected layout and
integrity behavior are documented in [DATASET_ACCESS.md](./DATASET_ACCESS.md).

## Running the harness

Commands below assume the current directory is the repository root and the
private dataset has been placed under `evaluation_harness/`.

### Smoke test

The default is a no-inference dry run. It validates the frozen files and shows
the one-case/one-task run plan without loading weights:

```powershell
python evaluation_harness\evaluation_runner.py --mode smoke --models qwen3_1_7b
```

To execute the smoke test with inference:

```powershell
python evaluation_harness\evaluation_runner.py --mode smoke --models qwen3_1_7b --execute
```

### Pilot evaluation

The pilot uses the ten case IDs in `track_a_benchmark_spec.json` and all five
tasks. Inspect the dry run first:

```powershell
python evaluation_harness\evaluation_runner.py --mode pilot --models qwen3_1_7b
```

Execute a pilot on one selected model:

```powershell
python evaluation_harness\evaluation_runner.py --mode pilot --models qwen3_1_7b --execute
```

### Full evaluation

The full mode selects every snapshot in the local `snapshots/` directory. By
default it runs all registered models and all tasks; select a subset with
`--models` for a smaller run.

```powershell
python evaluation_harness\evaluation_runner.py --mode full --models qwen3_1_7b --execute
```

Use `python evaluation_harness\evaluation_runner.py --help` for the supported
options, including quantization, dtype, generation settings, prefill behavior,
and output location. Do not use any option or edit that disables dataset
freeze verification; it is mandatory.

The harness defaults to `results/` under this folder. All results, progress
files, raw responses, and run metadata should remain local and are ignored by
Git.

## Prompts and schemas

`prompts/track_a/` contains the five shared task prompts:

- `initial_assessment.txt`
- `investigation_planning.txt`
- `evidence_analysis.txt`
- `investigation_decision.txt`
- `final_reporting.txt`

`schemas/` contains the corresponding JSON schemas and
`approved_action_catalogue.json`. The benchmark specification binds each task
to its prompt and schema. Every model uses the same common prompt and schema;
only `{evidence_json}` is replaced by the frozen case evidence. Prompt mode is
recorded as `official_common` and per-task prompt/schema SHA-256 hashes are
recorded in `run_metadata.json`. Each raw response file also records the hash
of the fully rendered prompt.

There are no model-specific prompt assets in the provided harness, so this
clean version does not expose an experimental model-specific prompt mode.
Experimental prompts, if introduced in a future separately reviewed change,
must be opt-in and must not be mixed with official common-prompt runs.

## Outputs and validation

Each run writes `evaluation_results.csv`, `evaluation_results.json`,
progress files, `run_metadata.json`, and a `raw/` folder. Validation and
performance fields include:

- JSON and schema validity.
- Evidence-reference validity.
- Per-response latency, prompt/generated token counts, and tokens per second.
- Peak GPU memory and prefill mode/chunk details where available.
- Errors and the run completion status.

Ground truth is used only by offline response validation (including checks for
ground-truth field and validation-note leakage). The current harness does not
calculate a fraud-classification score or other ground-truth accuracy metric.
Raw responses and output records contain case-level evidence and must not be
published.

## Dataset integrity and local tests

Before any run, the harness checks the complete snapshot set and SHA-256
digests against `track_a_dataset_manifest.json`, including the digest of the
local ground-truth file. Missing inputs, unexpected snapshots, or changed
content abort the run. The `--skip-freeze-check` bypass is intentionally not
available.

Run the local validation suite without downloading weights or reading private
dataset contents:

```powershell
python -m unittest discover -s evaluation_harness\tests -v
```
