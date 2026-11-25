# Gemma on the CyFinX FAA Framework — Benchmark Guide

This update adds telemetry and a repeatable multi-alert runner without changing
CyFinX's FAA investigation phases or its agent responsibilities.

## What is measured

For each investigation, the instrumented Gemma client records each model call's
stage, input-token count, output-token count, end-to-end call latency, output
tokens/second, and GPU memory allocated/reserved after the call. The framework
also records model-load time, investigation wall time, number of FAA steps,
Information-Gathering code execution time, code-generation retries, and Vision
Agent invocations. Prompt and response text are not copied into telemetry.

Stages are labelled as FAA Planning, FAA Information-Gathering code/repair,
FAA Analysis, RGA Stage 1, RGA Stage 2, Detective Agent, Vision Agent, and the
optional Evidence Quality Evaluation.

## Important interpretation

- `framework_wall_time_seconds` measures the FAA investigation through the
  RGA and Detective hand-off. It excludes model loading.
- `total_model_inference_seconds` sums model-call latency, including prompt
  tokenization and response decoding in the client.
- `overall_output_tokens_per_second` is total generated tokens divided by the
  summed model-call latency; it is a weighted run-level throughput.
- `run_peak_gpu_memory_allocated_gib` and `run_peak_gpu_memory_reserved_gib`
  are measured for the investigation after the model has loaded.
- `paused_max_steps` is not a completed investigation and has no RGA or
  Detective decision. Do not count it as a correct/incorrect final decision.
- This benchmark does not expose `Ground_Truth` to the investigation agents.
  Runtime/token/memory measurements are not classification accuracy. If
  accuracy is later calculated, use the separate evaluation dataset/database
  only after the investigation results have been saved.

## Run in the VS Code notebook connected to the Colab T4

1. Upload `CyFinX_Gemma_Performance_Update.zip` to the connected Colab runtime.
2. Run the updated notebook's first setup cell. It extracts ZIP entries while
   normalizing Windows backslash paths, then checks `/content/CyFinX/app/main.py`.
3. Mount Google Drive and set `CYFINX_OPERATIONAL_DB` before importing any
   `app` modules. The notebook copies the master SQLite database to Colab's
   local filesystem for the run.
4. Load Gemma once with `gemma = GemmaClient.load()`.
5. Run one known alert first (the existing notebook default is
   `ALT0000089`). Inspect the `performance_metrics` before starting a batch.
6. Preview alert IDs from `Fraud_Alerts`, choose 10, then run:

```python
from scripts.benchmark_gemma_framework import run_benchmark

ALERT_IDS = [
    # Put exactly 10 Alert_ID values here.
]
benchmark = run_benchmark(
    ALERT_IDS,
    max_steps=12,
    gemma_client=gemma,
    evaluate_evidence=False,
    output_dir="/content/drive/MyDrive/CyFinX/benchmarks/gemma_faa_10_alerts",
    resume=True,
)
```

The benchmark writes one JSON result per alert, `all_results.json`, and
`summary.csv` in the specified output directory. Point `output_dir` to Google
Drive so each completed case is checkpointed there. If Colab disconnects, rerun
with the same output directory and `resume=True`; completed cases are skipped.
Reuse the exact same 10 Alert_IDs and investigation settings for Qwen if a
full-framework model comparison is required.

## Local regression tests

From the CyFinX project root:

```powershell
python -m pytest -q
```
