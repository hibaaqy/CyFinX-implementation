from app.utils.performance_metrics import summarize_model_calls


def test_summarize_model_calls_aggregates_tokens_latency_and_stages():
    summary = summarize_model_calls([
        {
            "stage": "FAA Planning", "status": "success",
            "input_tokens": 100, "output_tokens": 20,
            "latency_seconds": 4.0, "gpu_memory_allocated_after_call_gib": 5.2,
            "gpu_memory_reserved_after_call_gib": 6.0,
        },
        {
            "stage": "FAA Planning", "status": "success",
            "input_tokens": 120, "output_tokens": 30,
            "latency_seconds": 6.0, "gpu_memory_allocated_after_call_gib": 5.5,
            "gpu_memory_reserved_after_call_gib": 6.1,
        },
        {
            "stage": "Detective Agent", "status": "error",
            "input_tokens": 80, "output_tokens": 0,
            "latency_seconds": 2.0, "gpu_memory_allocated_after_call_gib": None,
            "gpu_memory_reserved_after_call_gib": None,
        },
    ])

    assert summary["model_call_count"] == 3
    assert summary["successful_model_calls"] == 2
    assert summary["failed_model_calls"] == 1
    assert summary["total_input_tokens"] == 300
    assert summary["total_output_tokens"] == 50
    assert summary["total_model_inference_seconds"] == 10.0
    assert summary["overall_output_tokens_per_second"] == 5.0
    assert summary["max_gpu_memory_allocated_after_call_gib"] == 5.5
    assert summary["calls_by_stage"]["FAA Planning"]["calls"] == 2
    assert summary["calls_by_stage"]["Detective Agent"]["failed_calls"] == 1
