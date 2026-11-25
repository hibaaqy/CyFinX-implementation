"""Single entry point for the integrated CyFinX FAA investigation system."""

import argparse
import json
import re
from time import perf_counter
from pathlib import Path

from app.agents import (
    DetectiveAgent,
    EvidenceQualityEvaluator,
    FraudAnalystAssistant,
    ReportGenerator,
    VisionAgent,
)
from app.tools.function_calling_tool import FunctionCallingTool
from app.utils.performance_metrics import summarize_model_calls

ROOT = Path(__file__).resolve().parents[1]


def run_investigation(
    alert_id,
    max_steps=12,
    gemma_client=None,
    evaluate_evidence=False,
):
    """Run one complete FAA investigation using a Colab-loaded Gemma client.

    Pass gemma_client in tests/notebooks to reuse an already loaded model.
    If omitted, the Gemma model is loaded on the active CUDA runtime.
    """
    from app.database.connection import OPERATIONAL_DB_PATH
    if not OPERATIONAL_DB_PATH.is_file():
        raise FileNotFoundError(
            f"Operational database not found: {OPERATIONAL_DB_PATH}. "
            "Place cyfinx_operational_v1.db in data/database/ or set "
            "CYFINX_OPERATIONAL_DB before importing the application."
        )

    if gemma_client is None:
        from app.llm.gemma_client import GemmaClient
        gemma_client = GemmaClient.load()

    report_generator = ReportGenerator(gemma_client)
    detective_agent = DetectiveAgent(gemma_client)
    vision_agent = VisionAgent(gemma_client)
    function_calling_tool = FunctionCallingTool()
    function_calling_tool.register(
        name="image_to_text",
        description=(
            "Analyze one chart generated during the current FAA investigation "
            "step and return a case-specific visual interpretation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "chart_path": {"type": "string", "description": "Path to the generated chart image."},
                "case_context": {"type": "string", "description": "Alert and transaction context."},
                "investigative_lead": {"type": "string", "description": "The selected lead for this step."},
            },
            "required": ["chart_path", "case_context", "investigative_lead"],
        },
        handler=vision_agent.analyze,
    )

    # Capture per-investigation model telemetry. Gemma is loaded once and may
    # be reused across several alerts in a benchmark run.
    call_metrics = getattr(gemma_client, "call_metrics", [])
    first_call_index = len(call_metrics)
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        torch = None

    faa = FraudAnalystAssistant(
        gemma_client=gemma_client,
        report_generator=report_generator,
        detective_agent=detective_agent,
        function_calling_tool=function_calling_tool,
        step_output_dir=ROOT / "reports" / "step_artifacts",
    )

    framework_started = perf_counter()
    result = faa.investigate(alert_id=alert_id, max_steps=max_steps)
    framework_elapsed = perf_counter() - framework_started

    evidence_evaluation_seconds = 0.0
    if evaluate_evidence and result["status"] == "completed":
        evaluator = EvidenceQualityEvaluator(gemma_client)
        evaluation_started = perf_counter()
        result["evidence_quality_evaluation"] = evaluator.evaluate(
            result["reports"]["unfiltered_report"]
        )
        evidence_evaluation_seconds = perf_counter() - evaluation_started

    new_calls = list(getattr(gemma_client, "call_metrics", []))[first_call_index:]
    performance = summarize_model_calls(new_calls)
    performance.update({
        "framework_wall_time_seconds": round(framework_elapsed, 3),
        "optional_evidence_evaluation_seconds": round(evidence_evaluation_seconds, 3),
        "investigation_step_count": len(result.get("steps", [])),
        "information_gathering_execution_seconds": round(
            sum(
                float(step.get("information_gathering_execution_seconds") or 0)
                for step in result.get("steps", [])
            ),
            3,
        ),
        "code_generation_retry_count": sum(
            max(int(step.get("code_generation_attempts", 1)) - 1, 0)
            for step in result.get("steps", [])
        ),
        "vision_agent_invocations": sum(
            1 for step in result.get("steps", []) if step.get("vision_agent_invoked")
        ),
        "model_load": getattr(gemma_client, "load_metrics", {}),
    })
    try:
        if torch is not None and torch.cuda.is_available():
            performance["run_peak_gpu_memory_allocated_gib"] = round(
                torch.cuda.max_memory_allocated() / (1024 ** 3), 3
            )
            performance["run_peak_gpu_memory_reserved_gib"] = round(
                torch.cuda.max_memory_reserved() / (1024 ** 3), 3
            )
    except Exception:
        pass
    result["performance_metrics"] = performance

    safe_alert_id = re.sub(r"[^A-Za-z0-9_.-]", "_", alert_id)
    output_dir = ROOT / "reports" / safe_alert_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "investigation_result.json"
    result["saved_result_path"] = str(output_path)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run a dynamic FAA investigation for one CyFinX alert."
    )
    parser.add_argument(
        "--alert-id",
        required=True,
        help="Alert_ID from the operational Fraud_Alerts table.",
    )
    parser.add_argument(
        "--evaluate-evidence",
        action="store_true",
        help=(
            "Optionally evaluate every evidence point using the paper's "
            "four Likert-scale evidence-quality aspects."
        ),
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help=(
            "Safety cap. If the FAA still chooses continue at this limit, "
            "the investigation is paused without an RGA or Detective decision."
        ),
    )
    args = parser.parse_args()

    result = run_investigation(
        alert_id=args.alert_id,
        max_steps=args.max_steps,
        evaluate_evidence=args.evaluate_evidence,
    )

    print("\n" + "=" * 72)
    print("CYFINX FAA INVESTIGATION RESULT")
    print("=" * 72)
    print("Alert:", result["alert_id"])
    print("Status:", result["status"])

    if result["status"] == "completed":
        print("\nFINAL RGA REPORT:\n")
        print(result["reports"]["final_report"])
        print("\nDETECTIVE DECISION:\n")
        print(json.dumps(result["detective_decision"], indent=2, ensure_ascii=False))
    else:
        print("\n", result.get("message", "Investigation paused."))

    print("\nSaved result:", result["saved_result_path"])


if __name__ == "__main__":
    main()
