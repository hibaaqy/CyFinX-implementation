"""Run Gemma through the complete CyFinX FAA framework and save telemetry.

This benchmark uses only operational alert IDs. It deliberately does not load
Ground_Truth or expose evaluation labels to any investigation agent.
"""

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter

from app.main import run_investigation
from app.utils.performance_metrics import summarize_model_calls

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_benchmark(
    alert_ids,
    max_steps=12,
    gemma_client=None,
    evaluate_evidence=False,
    output_dir=None,
    resume=True,
):
    """Run one full FAA investigation per alert, reusing one Gemma instance."""
    alert_ids = [str(value).strip() for value in alert_ids if str(value).strip()]
    if not alert_ids:
        raise ValueError("Provide at least one Alert_ID.")
    if len(set(alert_ids)) != len(alert_ids):
        raise ValueError("Alert_ID list contains duplicates.")

    if gemma_client is None:
        from app.llm.gemma_client import GemmaClient
        gemma_client = GemmaClient.load()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if output_dir is None:
        output_dir = PROJECT_ROOT / "reports" / "benchmarks" / f"gemma_{timestamp}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_path = output_dir / "summary.csv"
    results_path = output_dir / "all_results.json"
    summary_by_alert = {}
    results_by_alert = {}
    if resume and summary_path.is_file():
        with summary_path.open("r", newline="", encoding="utf-8") as csv_file:
            for row in csv.DictReader(csv_file):
                summary_by_alert[row["alert_id"]] = row
    if resume and results_path.is_file():
        for item in json.loads(results_path.read_text(encoding="utf-8")):
            results_by_alert[item.get("alert_id", "")] = item

    completed_statuses = {"completed", "paused_max_steps"}
    for alert_id in alert_ids:
        previous = summary_by_alert.get(alert_id)
        if previous and previous.get("status") in completed_statuses:
            print(f"Skipping already completed benchmark case: {alert_id}")

    summary_rows = list(summary_by_alert.values())
    case_results = list(results_by_alert.values())

    for index, alert_id in enumerate(alert_ids, start=1):
        previous = summary_by_alert.get(alert_id)
        if previous and previous.get("status") in completed_statuses:
            continue
        print("\n" + "#" * 76)
        print(f"GEMMA FAA BENCHMARK — CASE {index}/{len(alert_ids)} — {alert_id}")
        print("#" * 76)
        call_metrics = getattr(gemma_client, "call_metrics", [])
        first_call_index = len(call_metrics)
        case_started = perf_counter()

        try:
            result = run_investigation(
                alert_id=alert_id,
                max_steps=max_steps,
                gemma_client=gemma_client,
                evaluate_evidence=evaluate_evidence,
            )
            case_elapsed = perf_counter() - case_started
            metrics = result.get("performance_metrics", {})
            status = result.get("status", "unknown")
            decision_obj = result.get("detective_decision") or {}
            decision = decision_obj.get("decision", "") if isinstance(decision_obj, dict) else ""
            error = ""
        except Exception as exc:
            case_elapsed = perf_counter() - case_started
            new_calls = list(getattr(gemma_client, "call_metrics", []))[first_call_index:]
            metrics = summarize_model_calls(new_calls)
            metrics["framework_wall_time_seconds"] = round(case_elapsed, 3)
            status = "error"
            decision = ""
            error = f"{type(exc).__name__}: {exc}"
            result = {
                "alert_id": alert_id,
                "status": status,
                "error": error,
                "performance_metrics": metrics,
            }
            print("CASE FAILED:", error)

        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", alert_id)
        case_path = output_dir / f"{safe_id}.json"
        case_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        row = {
            "alert_id": alert_id,
            "status": status,
            "decision": decision,
            "investigation_steps": len(result.get("steps", [])),
            "model_calls": metrics.get("model_call_count", 0),
            "successful_model_calls": metrics.get("successful_model_calls", 0),
            "failed_model_calls": metrics.get("failed_model_calls", 0),
            "input_tokens": metrics.get("total_input_tokens", 0),
            "output_tokens": metrics.get("total_output_tokens", 0),
            "model_inference_seconds": metrics.get("total_model_inference_seconds", 0),
            "average_call_latency_seconds": metrics.get("average_call_latency_seconds", 0),
            "output_tokens_per_second": metrics.get("overall_output_tokens_per_second", 0),
            "framework_wall_time_seconds": metrics.get("framework_wall_time_seconds", round(case_elapsed, 3)),
            "peak_gpu_memory_allocated_gib": metrics.get("run_peak_gpu_memory_allocated_gib") or metrics.get("max_gpu_memory_allocated_after_call_gib"),
            "code_execution_seconds": metrics.get("information_gathering_execution_seconds", 0),
            "code_generation_retries": metrics.get("code_generation_retry_count", 0),
            "vision_agent_invocations": metrics.get("vision_agent_invocations", 0),
            "error": error,
            "result_file": str(case_path),
        }
        summary_by_alert[alert_id] = row
        results_by_alert[alert_id] = result
        summary_rows = list(summary_by_alert.values())
        case_results = list(results_by_alert.values())

        # Checkpoint after every alert so a Colab disconnect does not erase
        # already completed cases when output_dir is on Google Drive.
        fieldnames = list(summary_rows[0].keys())
        with summary_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_rows)
        results_path.write_text(
            json.dumps(case_results, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        print("Case status:", status)
        print("Steps:", row["investigation_steps"], "| Model calls:", row["model_calls"])
        print("Wall time (s):", row["framework_wall_time_seconds"])

    benchmark_info = {
        "model": getattr(gemma_client, "load_metrics", {}).get(
            "model_id", "google/gemma-4-E2B-it"
        ),
        "model_load_metrics": getattr(gemma_client, "load_metrics", {}),
        "alert_ids": alert_ids,
        "max_steps_safety_cap": max_steps,
        "evaluate_evidence": evaluate_evidence,
        "ground_truth_used_during_investigation": False,
        "resume_enabled": bool(resume),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary_csv": str(summary_path),
        "all_results_json": str(results_path),
    }
    (output_dir / "benchmark_info.json").write_text(
        json.dumps(benchmark_info, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nBENCHMARK COMPLETE")
    print("Summary CSV:", summary_path)
    print("Full results:", results_path)
    return {
        "output_dir": str(output_dir),
        "summary_csv": str(summary_path),
        "all_results_json": str(results_path),
        "rows": summary_rows,
        "results": case_results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Gemma on complete CyFinX FAA investigations."
    )
    parser.add_argument(
        "--alert-ids",
        required=True,
        help="Comma-separated Alert_ID values, e.g. ALT0000089,ALT0000090",
    )
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--evaluate-evidence", action="store_true")
    args = parser.parse_args()
    ids = [value.strip() for value in args.alert_ids.split(",") if value.strip()]
    run_benchmark(
        alert_ids=ids,
        max_steps=args.max_steps,
        evaluate_evidence=args.evaluate_evidence,
    )


if __name__ == "__main__":
    main()
