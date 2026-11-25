"""Small, dependency-light helpers for summarising Gemma inference telemetry."""

from collections import defaultdict
from statistics import mean, median


def summarize_model_calls(calls):
    """Aggregate per-call Gemma telemetry without retaining prompt contents."""
    calls = list(calls or [])
    successful = [call for call in calls if call.get("status") == "success"]
    latencies = [float(call.get("latency_seconds") or 0) for call in successful]
    total_input = sum(int(call.get("input_tokens") or 0) for call in calls)
    total_output = sum(int(call.get("output_tokens") or 0) for call in calls)
    total_latency = sum(latencies)

    stages = defaultdict(list)
    for call in calls:
        stages[str(call.get("stage") or "unspecified")].append(call)

    stage_summary = {}
    for stage, stage_calls in sorted(stages.items()):
        stage_successful = [c for c in stage_calls if c.get("status") == "success"]
        stage_input = sum(int(c.get("input_tokens") or 0) for c in stage_calls)
        stage_output = sum(int(c.get("output_tokens") or 0) for c in stage_calls)
        stage_latency = sum(float(c.get("latency_seconds") or 0) for c in stage_successful)
        stage_summary[stage] = {
            "calls": len(stage_calls),
            "successful_calls": len(stage_successful),
            "failed_calls": len(stage_calls) - len(stage_successful),
            "input_tokens": stage_input,
            "output_tokens": stage_output,
            "inference_seconds": round(stage_latency, 3),
            "output_tokens_per_second": round(stage_output / stage_latency, 3)
            if stage_latency > 0 else 0.0,
        }

    allocated = [
        float(c["gpu_memory_allocated_after_call_gib"])
        for c in calls if c.get("gpu_memory_allocated_after_call_gib") is not None
    ]
    reserved = [
        float(c["gpu_memory_reserved_after_call_gib"])
        for c in calls if c.get("gpu_memory_reserved_after_call_gib") is not None
    ]

    return {
        "model_call_count": len(calls),
        "successful_model_calls": len(successful),
        "failed_model_calls": len(calls) - len(successful),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_model_inference_seconds": round(total_latency, 3),
        "average_call_latency_seconds": round(mean(latencies), 3) if latencies else 0.0,
        "median_call_latency_seconds": round(median(latencies), 3) if latencies else 0.0,
        "overall_output_tokens_per_second": round(total_output / total_latency, 3)
        if total_latency > 0 else 0.0,
        "max_gpu_memory_allocated_after_call_gib": max(allocated) if allocated else None,
        "max_gpu_memory_reserved_after_call_gib": max(reserved) if reserved else None,
        "calls_by_stage": stage_summary,
        "model_calls": calls,
    }
