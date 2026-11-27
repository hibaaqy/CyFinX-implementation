"""Model registry for the CyFinX Track A evaluation."""

MODEL_REGISTRY = {
    "qwen3_5_4b": {
        "name": "Qwen3.5 4B",
        "model_id": "Qwen/Qwen3.5-4B",
        "loader": "multimodal",
    },
    "qwen3_5_2b": {
        "name": "Qwen3.5 2B",
        "model_id": "Qwen/Qwen3.5-2B",
        "loader": "multimodal",
    },
    "granite_3_3_2b": {
        "name": "Granite 3.3 2B",
        "model_id": "ibm-granite/granite-3.3-2b-instruct",
        "loader": "causal",
    },
    "qwen3_1_7b": {
        "name": "Qwen3 1.7B",
        "model_id": "Qwen/Qwen3-1.7B",
        "loader": "causal",
    },
    "phi4_mini": {
        "name": "Phi-4-mini 3.8B",
        "model_id": "microsoft/Phi-4-mini-instruct",
        "loader": "causal",
        "trust_remote_code": False,
    },
    "ministral3_8b": {
        "name": "Ministral 3 8B Instruct",
        "model_id": "mistralai/Ministral-3-8B-Instruct-2512-BF16",
        "loader": "multimodal",
    },
    "gemma_4_e2b": {
        "name": "Gemma 4 E2B IT",
        "model_id": "google/gemma-4-E2B-it",
        "loader": "multimodal",
    },
}
