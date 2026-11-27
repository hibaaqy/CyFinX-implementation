#!/usr/bin/env python3
"""T4-aware sequential Track A runner for the CyFinX model evaluation.

Long prompts are first attempted with memory-efficient SDPA. If that kernel
is unavailable or the full prefill runs out of memory, the runner retries
using lossless chunked prefill and a carried KV cache. No evidence is dropped.
"""

import argparse
from contextlib import nullcontext
import csv
import gc
import hashlib
import io
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from model_registry import MODEL_REGISTRY


HARNESS_DIR = Path(__file__).resolve().parent
OFFICIAL_PROMPT_MODE = "official_common"

# Only identifiers belonging to evidence records may be cited by model output.
# Case/customer/account metadata identifiers are deliberately excluded.
ALLOWED_EVIDENCE_ID_FIELDS = {
    "Alert_ID",
    "Complaint_ID",
    "Transaction_ID",
    "Session_ID",
    "Device_ID",
    "Customer_Device_ID",
    "Beneficiary_ID",
    "KYC_ID",
    "Biometric_event_ID",
    "Auth_event_ID",
    "Agent_ID",
}

RESULT_FIELDS = [
    "run_id",
    "model_key",
    "model_id",
    "task",
    "case_id",
    "json_valid",
    "schema_valid",
    "evidence_references_valid",
    "latency_seconds",
    "prompt_tokens",
    "generated_tokens",
    "tokens_per_second",
    "peak_gpu_memory_bytes",
    "peak_gpu_memory_before_bytes",
    "prefill_mode_used",
    "prefill_chunks",
    "prefill_chunk_size",
    "error",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def task_prompt_hashes(tasks):
    return {
        task["name"]: {
            "prompt_sha256": sha256_file(Path(task["prompt_path"])),
            "schema_sha256": sha256_file(Path(task["schema_path"])),
        }
        for task in tasks
    }


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(value, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def verify_dataset_freeze():
    manifest_path = HARNESS_DIR / "track_a_dataset_manifest.json"
    if not manifest_path.exists():
        return ["missing:track_a_dataset_manifest.json"]

    try:
        manifest = load_json(manifest_path)
    except Exception as error:
        return [
            f"manifest_unreadable:{type(error).__name__}: {error}"
        ]

    mismatch = []
    expected_files = manifest.get("snapshot_sha256")
    if not isinstance(expected_files, dict):
        return ["manifest_invalid:snapshot_sha256 must be an object"]

    snapshot_dir = HARNESS_DIR / "snapshots"
    if not snapshot_dir.exists():
        mismatch.append("missing:snapshots directory")
    else:
        actual_files = {
            path.name for path in snapshot_dir.glob("*.json")
        }

        for filename in sorted(actual_files - set(expected_files)):
            mismatch.append(f"unexpected:{filename}")

        for filename, expected_hash in expected_files.items():
            snapshot_path = snapshot_dir / filename
            if not snapshot_path.exists():
                mismatch.append(f"missing:{filename}")
            elif sha256_file(snapshot_path) != expected_hash:
                mismatch.append(f"changed:{filename}")

    ground_truth_path = (
        HARNESS_DIR / "ground_truth" / "Ground_Truth.csv"
    )
    if not ground_truth_path.exists():
        mismatch.append("missing:ground_truth/Ground_Truth.csv")
    elif sha256_file(ground_truth_path) != manifest.get(
        "ground_truth_sha256"
    ):
        mismatch.append("ground_truth:changed")

    return mismatch


def collect_evidence_references(value):
    """Return only IDs belonging to explicitly approved evidence record types."""
    references = set()

    def walk(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in ALLOWED_EVIDENCE_ID_FIELDS:
                    if isinstance(child, str) and child:
                        references.add(child)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return references


def extract_json(text):
    """Extract the top-level JSON object from a model response.

    Only an object is accepted (every task schema has an object at the top).
    The old version scanned forward for ANY decodable "{" or "[" and so, when
    the real object was truncated or malformed, silently returned a nested
    fragment (for example an inner evidence list) that then failed schema
    validation with a misleading message. Now: if the first object cannot be
    decoded, the response is reported as invalid JSON.
    """
    if not isinstance(text, str):
        raise TypeError("model response is not text")

    text = text.strip().lstrip("\ufeff")
    if not text:
        raise ValueError("model response is empty")

    # Drop completed reasoning blocks. An unclosed block is left alone, so a
    # response that ran out of tokens while "thinking" correctly fails.
    text = re.sub(
        r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE
    ).strip()
    # Some chat templates end the generation prompt with "<think>", so the
    # response contains reasoning followed by a lone "</think>". Keep only
    # what comes after the last closing tag.
    if "</think>" in text.lower():
        text = re.split(r"</think>", text, flags=re.IGNORECASE)[-1].strip()
    elif "<think>" in text.lower():
        raise ValueError(
            "response ended inside an unclosed reasoning block; "
            "no final answer was produced (likely truncated)"
        )
    if not text:
        raise ValueError("model response contained only a reasoning block")

    # First try the complete response.
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
        raise ValueError(
            f"top-level JSON is {type(value).__name__}, expected an object"
        )
    except json.JSONDecodeError:
        pass

    fenced_blocks = re.findall(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for block in fenced_blocks:
        try:
            value = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    # Decode only from the FIRST "{". raw_decode handles nested objects and
    # braces inside strings.
    first_brace = text.find("{")
    if first_brace == -1:
        raise ValueError("no JSON object found in response")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[first_brace:])
    except json.JSONDecodeError as error:
        raise ValueError(
            "response contains a JSON object that is incomplete or "
            f"malformed ({error.msg} at char {error.pos}); likely truncated"
        ) from error
    if not isinstance(value, dict):
        raise ValueError("first JSON value in response is not an object")
    return value


def validate_schema_definition(schema):
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema package is not installed"]

    try:
        validator_class = jsonschema.validators.validator_for(schema)
        validator_class.check_schema(schema)
        return []
    except jsonschema.SchemaError as error:
        return [f"invalid schema: {error.message}"]


def validate_json_schema(value, schema):
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema package is not installed"]

    try:
        validator_class = jsonschema.validators.validator_for(schema)
        validator_class.check_schema(schema)
        validator = validator_class(schema)
        validation_errors = sorted(
            validator.iter_errors(value),
            key=lambda error: (
                list(error.absolute_path),
                error.message,
            ),
        )
        messages = []
        for error in validation_errors[:20]:
            location = ".".join(
                str(part) for part in error.absolute_path
            )
            prefix = f"{location}: " if location else ""
            messages.append(prefix + error.message)

        if len(validation_errors) > 20:
            messages.append(
                f"{len(validation_errors) - 20} additional schema errors omitted"
            )
        return messages
    except jsonschema.SchemaError as error:
        return [f"invalid schema: {error.message}"]


def load_ground_truth(path):
    """Load GT for offline checks only. This data is never passed to prompts."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "Case_ID" not in reader.fieldnames:
            raise ValueError("Ground_Truth.csv must contain a Case_ID column")

        rows = {}
        for row in reader:
            case_id = row.get("Case_ID", "")
            if not case_id:
                continue
            if case_id in rows:
                raise ValueError(
                    f"duplicate Case_ID in Ground_Truth.csv: {case_id}"
                )
            rows[case_id] = row
    return rows


def validate_response(parsed, snapshot, ground_truth_row=None):
    """Validate case identity, evidence-reference IDs, and obvious GT leakage."""
    errors = []
    if not isinstance(parsed, dict):
        return ["top-level JSON must be an object"]

    expected_case_id = snapshot.get("case", {}).get("Case_ID")
    if parsed.get("case_id") != expected_case_id:
        errors.append("case_id does not match snapshot")

    response_references = set()

    def walk_response(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "evidence_references" and isinstance(value, list):
                    response_references.update(
                        item for item in value if isinstance(item, str)
                    )
                if isinstance(value, (dict, list)):
                    walk_response(value)
        elif isinstance(node, list):
            for item in node:
                walk_response(item)

    walk_response(parsed)

    valid_references = collect_evidence_references(snapshot)
    invalid_references = sorted(
        response_references - valid_references
    )
    if invalid_references:
        errors.append(
            "unknown evidence references: "
            + ", ".join(invalid_references)
        )

    # Detect use of GT-only field names. Do not scan binary is_fraud values
    # such as "0" or "1": those occur naturally throughout ordinary JSON.
    forbidden_fields = {
        "is_fraud",
        "Fraud_type",
        "Scenario_ID",
        "Validation_notes",
    }
    response_keys = set()

    def collect_keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                response_keys.add(key)
                collect_keys(value)
        elif isinstance(node, list):
            for item in node:
                collect_keys(item)

    collect_keys(parsed)
    for field in sorted(forbidden_fields & response_keys):
        errors.append(f"ground-truth field leaked: {field}")

    # Scenario IDs and long validation notes are case-specific GT values.
    # Fraud_type is not scanned because a model may independently infer a
    # common fraud category from the evidence; a match alone proves no leak.
    serialized = json.dumps(parsed, ensure_ascii=False)
    if ground_truth_row:
        scenario_id = ground_truth_row.get("Scenario_ID", "")
        if (
            scenario_id
            and len(scenario_id) >= 6
            and scenario_id in serialized
        ):
            errors.append("potential ground-truth Scenario_ID leaked")

        validation_notes = ground_truth_row.get("Validation_notes", "")
        if (
            validation_notes
            and len(validation_notes) >= 40
            and validation_notes in serialized
        ):
            errors.append("potential ground-truth Validation_notes leaked")

    return errors


def _load_with_relaxed_attention(
    model_class, config, kwargs, attention_backend,
    trust_remote_code, revision, first_error,
):
    """Retry a composite model whose audio/vision tower lacks SDPA support.

    First keep SDPA for the text model and use eager attention only for
    audio sub-models (they are unused for this text-only benchmark). Only if
    that fails, fall back to eager attention everywhere.
    """
    from transformers import AutoConfig

    options = []
    try:
        model_config = AutoConfig.from_pretrained(
            config["model_id"],
            trust_remote_code=trust_remote_code,
            **({"revision": revision} if revision else {}),
        )
        audio_parts = [
            name for name in getattr(model_config, "sub_configs", {})
            if "audio" in name
        ]
        if audio_parts:
            options.append({
                "": attention_backend,
                **{name: "eager" for name in audio_parts},
            })
    except Exception:
        pass
    options.append("eager")

    last_error = first_error
    for option in options:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        try:
            model = model_class.from_pretrained(
                config["model_id"],
                **{**kwargs, "attn_implementation": option},
            )
            print(f"Loaded with attn_implementation={option!r}", flush=True)
            return model
        except ValueError as error:
            last_error = error
    raise last_error


def load_model(config, quantization, dtype, attention_backend="sdpa"):
    import torch

    trust_remote_code = config.get("trust_remote_code", False)
    revision = config.get("revision")

    kwargs = {
        "trust_remote_code": trust_remote_code,
        # SDPA allows PyTorch to select a fused attention kernel when the
        # active GPU supports it. The T4 fallback below also works without it.
        "attn_implementation": attention_backend,
        # Force fp16 for ALL branches, including 4bit/8bit. Without this,
        # Transformers 5.x loads the non-quantized layers in the checkpoint
        # dtype (bf16), which the T4 cannot run through the memory-efficient
        # SDPA kernel and which causes full NxN attention and OOM.
        "dtype": torch.float16,
    }
    if revision:
        kwargs["revision"] = revision

    if quantization == "4bit":
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        kwargs["device_map"] = "auto"
    elif quantization == "8bit":
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_8bit=True
        )
        kwargs["device_map"] = "auto"
    else:
        effective_dtype = (
            "bfloat16" if quantization == "bf16"
            else "float16" if quantization == "fp16"
            else dtype
        )
        kwargs["dtype"] = getattr(torch, effective_dtype)
        kwargs["device_map"] = "auto"

    if config["loader"] == "causal":
        from transformers import AutoModelForCausalLM, AutoTokenizer

        processor = AutoTokenizer.from_pretrained(
            config["model_id"],
            trust_remote_code=trust_remote_code,
            **({"revision": revision} if revision else {}),
        )
        model = AutoModelForCausalLM.from_pretrained(
            config["model_id"],
            **kwargs,
        )
    elif config["loader"] == "multimodal":
        from transformers import AutoProcessor

        try:
            from transformers import AutoModelForMultimodalLM
            multimodal_class = AutoModelForMultimodalLM
        except ImportError:
            try:
                from transformers import AutoModelForImageTextToText
                multimodal_class = AutoModelForImageTextToText
            except ImportError as error:
                raise RuntimeError(
                    "This Transformers version has no supported "
                    "multimodal model class."
                ) from error

        processor = AutoProcessor.from_pretrained(
            config["model_id"],
            trust_remote_code=trust_remote_code,
            **({"revision": revision} if revision else {}),
        )
        try:
            model = multimodal_class.from_pretrained(
                config["model_id"],
                **kwargs,
            )
        except ValueError as error:
            if "does not support an attention implementation" not in str(error):
                raise
            model = _load_with_relaxed_attention(
                multimodal_class,
                config,
                kwargs,
                attention_backend,
                trust_remote_code,
                revision,
                error,
            )
    else:
        raise RuntimeError(
            f"Unsupported loader type: {config['loader']}"
        )

    return model, processor


def release_gpu_memory(torch_module):
    gc.collect()
    if torch_module is not None and torch_module.cuda.is_available():
        try:
            torch_module.cuda.empty_cache()
            torch_module.cuda.reset_peak_memory_stats()
        except Exception:
            # Cleanup should not hide the original model/generation error.
            pass


def build_prompt(template, snapshot, schema, snapshot_text=None):
    if template.count("{evidence_json}") != 1:
        raise ValueError(
            "task prompt must contain {evidence_json} exactly once"
        )

    evidence_json = (
        snapshot_text
        if snapshot_text is not None
        else json.dumps(snapshot, ensure_ascii=False)
    )
    schema_json = json.dumps(schema, ensure_ascii=False)
    instructions = template.replace("{evidence_json}", evidence_json)
    instructions += (
        "\n\nReturn a JSON object that exactly validates against this schema:\n"
        + schema_json
    )
    return instructions


def get_model_input_device(model):
    try:
        embedding = model.get_input_embeddings()
        if embedding is not None:
            device = embedding.weight.device
            if str(device) != "meta":
                return device
    except Exception:
        pass

    try:
        return model.device
    except Exception:
        return "cuda:0"


def prepare_model_inputs(processor, prompt, enable_thinking=False):
    """Apply the model chat template where available, with safe text fallbacks."""
    messages = [{"role": "user", "content": prompt}]
    tokenizer = getattr(processor, "tokenizer", processor)

    candidates = []
    for candidate in (processor, tokenizer):
        if candidate is not None and all(
            candidate is not existing for existing in candidates
        ):
            candidates.append(candidate)

    last_error = None
    for candidate in candidates:
        apply_template = getattr(candidate, "apply_chat_template", None)
        if not callable(apply_template):
            continue

        try:
            inputs = apply_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
                # Templates without a thinking switch ignore this kwarg, so
                # every model gets the same protocol.
                enable_thinking=enable_thinking,
            )
            if isinstance(inputs, str):
                inputs = candidate(
                    text=inputs,
                    return_tensors="pt",
                )
            return inputs
        except Exception as error:
            last_error = error

        try:
            rendered = apply_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=enable_thinking,
            )
            text_processor = (
                processor
                if callable(processor)
                else candidate
            )
            return text_processor(
                text=rendered,
                return_tensors="pt",
            )
        except Exception as error:
            last_error = error

    if hasattr(tokenizer, "encode"):
        return {
            "input_ids": tokenizer.encode(
                prompt,
                add_special_tokens=True,
                return_tensors="pt",
            )
        }

    if callable(processor):
        try:
            return processor(text=prompt, return_tensors="pt")
        except Exception as error:
            last_error = error

    raise RuntimeError(
        "could not prepare model inputs"
        + (
            f": {type(last_error).__name__}: {last_error}"
            if last_error else ""
        )
    )


def efficient_attention_context(torch_module):
    """Force PyTorch's memory-efficient SDPA kernel for a full-prompt attempt."""
    try:
        from torch.nn.attention import sdpa_kernel, SDPBackend
        return sdpa_kernel(SDPBackend.EFFICIENT_ATTENTION)
    except (ImportError, AttributeError):
        # Compatibility path for older PyTorch builds.
        return torch_module.backends.cuda.sdp_kernel(
            enable_flash=False,
            enable_math=False,
            enable_mem_efficient=True,
        )


def _cuda_cleanup(torch_module):
    gc.collect()
    if torch_module.cuda.is_available():
        try:
            torch_module.cuda.empty_cache()
        except Exception:
            pass


def _run_full_generation(model, inputs, generation_kwargs, torch_module):
    """Run the original one-pass prompt using memory-efficient SDPA."""
    context = (
        efficient_attention_context(torch_module)
        if torch_module.cuda.is_available()
        else nullcontext()
    )
    with context:
        with torch_module.inference_mode():
            return model.generate(**inputs, **generation_kwargs)


def _build_chunked_prefill_cache(model, inputs, chunk_size, torch_module):
    """Prefill all but the final prompt token in chunks, preserving KV state.

    The model sees every original input token in its original order. Chunking
    changes only the size of each forward pass; it does not summarize, filter,
    truncate, or rewrite evidence.
    """
    input_ids = inputs.get("input_ids")
    if input_ids is None:
        raise RuntimeError("chunked prefill requires input_ids")

    sequence_length = int(input_ids.shape[-1])
    prefill_length = sequence_length - 1  # reserve last token for generate()
    if prefill_length <= 0:
        return None, 0

    attention_mask = inputs.get("attention_mask")
    if attention_mask is None:
        attention_mask = torch_module.ones_like(input_ids)

    if not callable(getattr(model, "prepare_inputs_for_generation", None)):
        raise RuntimeError(
            "this model does not expose prepare_inputs_for_generation; "
            "cannot safely use chunked prefill"
        )

    # Include every sequence-aligned processor field (for example position or
    # token-type IDs) in each prefix. Non-sequence fields are passed unchanged.
    extra_inputs = {
        key: value for key, value in inputs.items()
        if key not in {"input_ids", "attention_mask", "past_key_values", "cache_position"}
    }

    chunk_ends = list(range(chunk_size, prefill_length + 1, chunk_size))
    if not chunk_ends or chunk_ends[-1] != prefill_length:
        chunk_ends.append(prefill_length)

    past_key_values = None
    chunk_start = 0
    for end in chunk_ends:
        prefix_ids = input_ids[:, :end]
        prefix_mask = attention_mask[:, :end]
        chunk_extra = {}
        for key, value in extra_inputs.items():
            if (
                torch_module.is_tensor(value)
                and value.ndim >= 2
                and value.shape[-1] == sequence_length
            ):
                chunk_extra[key] = value[..., :end]
            else:
                chunk_extra[key] = value

        # cache_position supplies absolute token positions, while
        # next_sequence_length below performs the actual input slicing. In
        # Transformers 5.x these are separate responsibilities: cache_position
        # alone does NOT trim a growing prefix to its unprocessed chunk.
        cache_position = torch_module.arange(
            chunk_start,
            end,
            dtype=torch_module.long,
            device=input_ids.device,
        )
        chunk_length = end - chunk_start
        prepared = model.prepare_inputs_for_generation(
            input_ids=prefix_ids,
            # Transformers 5.x does not infer the chunk length from
            # cache_position. Without this argument its generic preparation
            # method forwards the ENTIRE growing prefix on every iteration,
            # duplicating cached tokens and eventually exhausting VRAM.
            next_sequence_length=chunk_length,
            attention_mask=prefix_mask,
            past_key_values=past_key_values,
            cache_position=cache_position,
            use_cache=True,
            **chunk_extra,
        )
        prepared_ids = prepared.get("input_ids")
        if prepared_ids is not None and int(prepared_ids.shape[-1]) != chunk_length:
            raise RuntimeError(
                "chunked prefill safety check failed: model preparation returned "
                f"{int(prepared_ids.shape[-1])} input tokens for a "
                f"{chunk_length}-token chunk; refusing to duplicate cached tokens"
            )
        with torch_module.inference_mode():
            outputs = model(**prepared, return_dict=True)

        past_key_values = getattr(outputs, "past_key_values", None)
        if past_key_values is None:
            raise RuntimeError(
                "model did not return past_key_values during chunked prefill"
            )

        chunk_start = end
        del outputs, prepared, prefix_ids, prefix_mask, chunk_extra

    return past_key_values, len(chunk_ends)


def _model_context_limit(model):
    """Return the declared text context limit, if the config exposes one."""
    configs = []
    config = getattr(model, "config", None)
    text_config = getattr(config, "text_config", None)
    if text_config is not None:
        configs.append(text_config)
    if config is not None:
        configs.append(config)

    for candidate in configs:
        for field in (
            "max_position_embeddings",
            "max_sequence_length",
            "n_positions",
            "seq_length",
        ):
            value = getattr(candidate, field, None)
            if isinstance(value, int) and value > 0:
                return value
    return None


def generate_response(model, processor, prompt, args):
    import torch

    inputs = prepare_model_inputs(
        processor, prompt, getattr(args, "enable_thinking", False)
    )
    input_device = get_model_input_device(model)

    if hasattr(inputs, "to"):
        inputs = inputs.to(input_device)
    if not isinstance(inputs, dict):
        if hasattr(inputs, "items"):
            inputs = dict(inputs.items())
        else:
            raise TypeError(
                f"unsupported model input type: {type(inputs).__name__}"
            )
    else:
        inputs = {
            key: value.to(input_device) if hasattr(value, "to") else value
            for key, value in inputs.items()
        }

    input_ids = inputs.get("input_ids")
    if input_ids is None:
        raise RuntimeError("tokenized prompt does not contain input_ids")

    prompt_tokens = int(input_ids.shape[-1])
    context_limit = _model_context_limit(model)
    if context_limit is not None and prompt_tokens > context_limit:
        print(
            f"WARNING: prompt has {prompt_tokens:,} tokens, exceeding "
            f"the model's declared {context_limit:,}-token context. "
            "No evidence will be truncated; this model may reject the request.",
            flush=True,
        )

    do_sample = args.temperature > 0
    generation_kwargs = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": do_sample,
        "use_cache": True,
    }
    if do_sample:
        generation_kwargs["temperature"] = args.temperature
        generation_kwargs["top_p"] = args.top_p

    cuda_available = torch.cuda.is_available()
    device_index = torch.cuda.current_device() if cuda_available else None
    peak_memory_before = None
    if cuda_available:
        torch.cuda.synchronize(device_index)
        torch.cuda.reset_peak_memory_stats(device_index)
        peak_memory_before = torch.cuda.memory_allocated(device_index)

    started = time.perf_counter()
    output = None
    cache = None
    prefill_chunks = 0
    prefill_mode_used = None
    first_attempt_peak = 0
    first_attempt_error = None

    try:
        try_full_prefill = args.prefill_mode == "full" or (
            args.prefill_mode == "auto"
            and not getattr(args, "_auto_fallback_to_chunked", False)
        )
        if try_full_prefill:
            try:
                output = _run_full_generation(
                    model, inputs, generation_kwargs, torch
                )
                prefill_mode_used = "full_efficient_sdpa"
                prefill_chunks = 1
            except Exception as first_error:
                first_error_text = (
                    f"{type(first_error).__name__}: {first_error}"
                )
                first_attempt_error = first_error_text
                if cuda_available:
                    try:
                        first_attempt_peak = torch.cuda.max_memory_allocated(
                            device_index
                        )
                    except Exception:
                        first_attempt_peak = 0
                output = None
                _cuda_cleanup(torch)

                if args.prefill_mode == "full":
                    raise RuntimeError(
                        "full-context efficient SDPA failed: "
                        + first_error_text
                    ) from first_error

                if args.prefill_mode == "auto":
                    # Once the full-context kernel fails for this model, do not
                    # waste time repeating the same failed attempt on every case.
                    args._auto_fallback_to_chunked = True

                print(
                    "Full-context SDPA did not fit or was unsupported; "
                    "retrying with lossless chunked prefill. "
                    f"Reason: {first_error_text}",
                    flush=True,
                )

        if output is None:
            if cuda_available:
                torch.cuda.reset_peak_memory_stats(device_index)
            try:
                cache, prefill_chunks = _build_chunked_prefill_cache(
                    model,
                    inputs,
                    args.prefill_chunk_size,
                    torch,
                )
                generation_inputs = dict(inputs)
                if cache is not None:
                    generation_inputs["past_key_values"] = cache
                    # The cache contains all prompt tokens except the final one.
                    # Seed generation at that single uncached position so the
                    # prompt is not recomputed after chunked prefill.
                    generation_inputs["cache_position"] = torch.arange(
                        prompt_tokens - 1,
                        prompt_tokens,
                        dtype=torch.long,
                        device=input_ids.device,
                    )

                with torch.inference_mode():
                    try:
                        output = model.generate(
                            **generation_inputs,
                            **generation_kwargs,
                        )
                    except ValueError as generate_error:
                        # Some architectures (e.g. Gemma 4) reject an explicit
                        # cache_position. generate() derives it from the carried
                        # cache length anyway, and this validation error is
                        # raised before any compute, so the cache is intact.
                        message = str(generate_error)
                        if (
                            "cache_position" in generation_inputs
                            and "not used by the model" in message
                            and "cache_position" in message
                        ):
                            generation_inputs.pop("cache_position")
                            output = model.generate(
                                **generation_inputs,
                                **generation_kwargs,
                            )
                        else:
                            raise
                del generation_inputs
            except Exception as chunk_error:
                chunk_error_text = (
                    f"{type(chunk_error).__name__}: {chunk_error}"
                )
                if first_attempt_error:
                    raise RuntimeError(
                        "chunked prefill/generation failed: "
                        + chunk_error_text
                        + " | initial full-context attempt failed: "
                        + first_attempt_error
                    ) from chunk_error
                raise
            prefill_mode_used = (
                "chunked_fallback"
                if args.prefill_mode == "auto"
                else "chunked"
            )

        if cuda_available:
            torch.cuda.synchronize(device_index)
        elapsed = time.perf_counter() - started

        output_ids = getattr(output, "sequences", output)
        peak_memory = (
            torch.cuda.max_memory_allocated(device_index)
            if cuda_available else None
        )
        if peak_memory is not None:
            peak_memory = max(peak_memory, first_attempt_peak)

        is_encoder_decoder = bool(
            getattr(getattr(model, "config", None), "is_encoder_decoder", False)
        )
        if is_encoder_decoder:
            generated_ids = output_ids[0]
        else:
            generated_ids = output_ids[0][prompt_tokens:]

        decoder = (
            processor
            if hasattr(processor, "batch_decode")
            or hasattr(processor, "decode")
            else getattr(processor, "tokenizer", processor)
        )
        if hasattr(decoder, "batch_decode"):
            text = decoder.batch_decode(
                [generated_ids],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
        elif hasattr(decoder, "decode"):
            text = decoder.decode(
                generated_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
        else:
            raise RuntimeError("processor has no supported decode method")

        generated_tokens = int(generated_ids.shape[-1])
        return {
            "text": text,
            "latency_seconds": elapsed,
            "prompt_tokens": prompt_tokens,
            "generated_tokens": generated_tokens,
            "tokens_per_second": (
                generated_tokens / elapsed if elapsed > 0 else None
            ),
            "peak_gpu_memory_bytes": peak_memory,
            "peak_gpu_memory_before_bytes": peak_memory_before,
            "prefill_mode_used": prefill_mode_used,
            "prefill_chunks": prefill_chunks,
            "prefill_chunk_size": args.prefill_chunk_size,
        }
    finally:
        output = None
        cache = None
        inputs = None
        gc.collect()
        if cuda_available:
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass


def initialize_progress_files(results_dir):
    progress_csv = results_dir / "evaluation_results_progress.csv"
    progress_jsonl = results_dir / "evaluation_results_progress.jsonl"

    with progress_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()

    progress_jsonl.write_text("", encoding="utf-8")
    return progress_csv, progress_jsonl


def append_progress_row(row, progress_paths):
    progress_csv, progress_jsonl = progress_paths

    with progress_csv.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writerow({
            key: row.get(key, "") for key in RESULT_FIELDS
        })
        handle.flush()
        os.fsync(handle.fileno())

    with progress_jsonl.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_final_results(rows, results_dir):
    csv_path = results_dir / "evaluation_results.csv"
    json_path = results_dir / "evaluation_results.json"

    csv_temp = csv_path.with_suffix(".csv.tmp")
    with csv_temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: row.get(key, "") for key in RESULT_FIELDS
            })
    os.replace(csv_temp, csv_path)

    write_json_atomic(rows, json_path)
    return csv_path, json_path


def prepare_tasks(tasks):
    prepared = []
    for task in tasks:
        prompt_path = HARNESS_DIR / task["prompt"]
        schema_path = HARNESS_DIR / task["schema"]

        if not prompt_path.exists():
            raise FileNotFoundError(f"missing task prompt: {prompt_path}")
        if not schema_path.exists():
            raise FileNotFoundError(f"missing task schema: {schema_path}")

        template = prompt_path.read_text(encoding="utf-8")
        if template.count("{evidence_json}") != 1:
            raise ValueError(
                f"{task['name']} prompt must contain "
                "{evidence_json} exactly once"
            )

        schema = load_json(schema_path)
        if not isinstance(schema, dict):
            raise ValueError(
                f"{task['name']} schema must be a JSON object"
            )

        prepared.append({
            "name": task["name"],
            "template": template,
            "schema": schema,
            "prompt_path": str(prompt_path),
            "schema_path": str(schema_path),
        })
    return prepared


def preflight_cases(case_ids):
    if not case_ids:
        raise ValueError("no cases selected")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case selection contains duplicate IDs")

    snapshot_dir = HARNESS_DIR / "snapshots"
    for case_id in case_ids:
        snapshot_path = snapshot_dir / f"{case_id}.json"
        if not snapshot_path.exists():
            raise FileNotFoundError(
                f"missing snapshot for selected case: {case_id}"
            )
        snapshot = load_json(snapshot_path)
        actual_case_id = snapshot.get("case", {}).get("Case_ID")
        if actual_case_id != case_id:
            raise ValueError(
                f"snapshot filename/case ID mismatch: {case_id} "
                f"contains {actual_case_id!r}"
            )


def seed_everything(seed, torch_module):
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass

    torch_module.manual_seed(seed)
    if torch_module.cuda.is_available():
        torch_module.cuda.manual_seed_all(seed)


def positive_int(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonnegative_float(value):
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def probability(value):
    parsed = float(value)
    if not 0 < parsed <= 1:
        raise argparse.ArgumentTypeError("must be greater than 0 and at most 1")
    return parsed


def main():
    parser = argparse.ArgumentParser(
        description="Run the frozen CyFinX Track A benchmark sequentially."
    )
    parser.add_argument(
        "--mode",
        choices=["smoke", "pilot", "full"],
        default="pilot",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODEL_REGISTRY.keys()),
        help="Default: all registered models.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--quantization",
        choices=["4bit", "8bit", "bf16", "fp16"],
        default="4bit",
    )
    parser.add_argument(
        "--dtype",
        choices=["float16", "bfloat16"],
        default="float16",
    )
    parser.add_argument(
        "--temperature",
        type=nonnegative_float,
        default=0.0,
    )
    parser.add_argument("--top-p", type=probability, default=1.0)
    parser.add_argument(
        "--max-new-tokens",
        type=positive_int,
        default=1024,
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help=(
            "Allow reasoning mode on models whose chat template supports it "
            "(Qwen3, Qwen3.5). Default: off for every model, so all models "
            "answer directly under the same protocol."
        ),
    )
    parser.add_argument(
        "--prefill-mode",
        choices=["auto", "chunked", "full"],
        default="auto",
        help=(
            "auto tries memory-efficient full-context SDPA, then falls back "
            "to lossless chunked prefill; chunked skips the full attempt"
        ),
    )
    parser.add_argument(
        "--prefill-chunk-size",
        type=positive_int,
        default=256,
        help="Token chunk size used by the lossless T4 prefill fallback.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output",
        default="evaluation_harness/results",
    )
    args = parser.parse_args()

    if args.models and len(args.models) != len(set(args.models)):
        parser.error("--models contains duplicate model keys")

    freeze_mismatches = verify_dataset_freeze()
    if freeze_mismatches:
        print(json.dumps({
            "error": "dataset freeze mismatch",
            "mismatches": freeze_mismatches,
        }, indent=2))
        return 1

    spec_path = HARNESS_DIR / "track_a_benchmark_spec.json"
    if not spec_path.exists():
        print(json.dumps({
            "error": "missing track_a_benchmark_spec.json",
        }, indent=2))
        return 1

    try:
        spec = load_json(spec_path)
        if args.mode == "smoke":
            if not spec.get("pilot_cases"):
                raise ValueError("benchmark spec has no pilot_cases")
            case_ids = [spec["pilot_cases"][0]]
            tasks_from_spec = [
                task for task in spec["tasks"]
                if task["name"] == "initial_assessment"
            ]
            if not tasks_from_spec:
                raise ValueError(
                    "benchmark spec has no initial_assessment task"
                )
        elif args.mode == "pilot":
            case_ids = spec["pilot_cases"]
            tasks_from_spec = spec["tasks"]
        else:
            case_ids = sorted(
                path.stem
                for path in (HARNESS_DIR / "snapshots").glob("*.json")
            )
            tasks_from_spec = spec["tasks"]

        preflight_cases(case_ids)
        tasks = prepare_tasks(tasks_from_spec)
    except Exception as error:
        print(json.dumps({
            "error": f"preflight_failed: {type(error).__name__}: {error}",
        }, indent=2))
        return 1

    model_keys = args.models or list(MODEL_REGISTRY.keys())

    if not args.execute:
        print(json.dumps({
            "status": "dry_run",
            "mode": args.mode,
            "prompt_mode": OFFICIAL_PROMPT_MODE,
            "prompt_hashes": task_prompt_hashes(tasks),
            "case_count": len(case_ids),
            "task_count": len(tasks),
            "model_count": len(model_keys),
            "expected_response_count": (
                len(case_ids) * len(tasks) * len(model_keys)
            ),
            "cases": case_ids,
            "tasks": [task["name"] for task in tasks],
            "models": [
                {
                    "key": key,
                    "name": MODEL_REGISTRY[key]["name"],
                    "model_id": MODEL_REGISTRY[key]["model_id"],
                    "loader": MODEL_REGISTRY[key]["loader"],
                }
                for key in model_keys
            ],
            "generation": {
                "temperature": args.temperature,
                "top_p": args.top_p,
                "max_new_tokens": args.max_new_tokens,
                "seed": args.seed,
                "quantization": args.quantization,
                "dtype": args.dtype,
                "prefill_mode": args.prefill_mode,
                "prefill_chunk_size": args.prefill_chunk_size,
            },
            "warning": "No model was loaded. Add --execute to run.",
        }, indent=2))
        return 0

    try:
        import torch
        import transformers
        import jsonschema  # noqa: F401
    except ImportError as error:
        print(json.dumps({
            "error": f"missing required dependency: {error}",
        }, indent=2))
        return 1

    schema_errors = []
    for task in tasks:
        errors = validate_schema_definition(task["schema"])
        if errors:
            schema_errors.append({
                "task": task["name"],
                "errors": errors,
            })
    if schema_errors:
        print(json.dumps({
            "error": "invalid task schema definitions",
            "details": schema_errors,
        }, indent=2))
        return 1

    if (
        args.quantization == "bf16"
        and torch.cuda.is_available()
        and torch.cuda.get_device_capability()[0] < 8
    ):
        print(json.dumps({
            "error": (
                "bf16 was requested, but the active GPU does not support "
                "bfloat16. Use --quantization 4bit or --quantization fp16."
            ),
        }, indent=2))
        return 1

    ground_truth_path = (
        HARNESS_DIR / "ground_truth" / "Ground_Truth.csv"
    )
    if not ground_truth_path.exists():
        print(json.dumps({
            "error": "missing ground_truth/Ground_Truth.csv",
        }, indent=2))
        return 1

    try:
        ground_truth_by_case = load_ground_truth(ground_truth_path)
        missing_gt_cases = sorted(
            set(case_ids) - set(ground_truth_by_case)
        )
        if missing_gt_cases:
            raise ValueError(
                "selected cases missing from Ground_Truth.csv: "
                + ", ".join(missing_gt_cases)
            )
    except Exception as error:
        print(json.dumps({
            "error": f"ground_truth_preflight_failed: {error}",
        }, indent=2))
        return 1

    output_dir = Path(args.output).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S_%fZ"
    )
    run_id = f"track_a_{args.mode}_{timestamp}"
    results_dir = output_dir / run_id
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    progress_paths = initialize_progress_files(results_dir)

    if args.quantization == "4bit":
        effective_dtype = "float16 (4-bit compute)"
    elif args.quantization == "8bit":
        effective_dtype = "bitsandbytes 8-bit"
    elif args.quantization == "bf16":
        effective_dtype = "bfloat16"
    elif args.quantization == "fp16":
        effective_dtype = "float16"
    else:
        effective_dtype = args.dtype

    run_metadata = {
        "run_id": run_id,
        "benchmark": "CyFinX Track A",
        "mode": args.mode,
        "prompt_mode": OFFICIAL_PROMPT_MODE,
        "prompt_hashes": task_prompt_hashes(tasks),
        "status": "running",
        "started_at": utc_now(),
        "case_ids": case_ids,
        "task_names": [task["name"] for task in tasks],
        "model_ids": {
            key: MODEL_REGISTRY[key]["model_id"]
            for key in model_keys
        },
        "model_revisions": {
            key: MODEL_REGISTRY[key].get("revision")
            for key in model_keys
        },
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_new_tokens": args.max_new_tokens,
        "prefill_mode": args.prefill_mode,
        "prefill_chunk_size": args.prefill_chunk_size,
        "enable_thinking": args.enable_thinking,
        "seed": args.seed,
        "quantization": args.quantization,
        "effective_dtype": effective_dtype,
        "pytorch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "python_version": sys.version,
        "gpu_name": (
            torch.cuda.get_device_name(0)
            if torch.cuda.is_available() else None
        ),
        "expected_response_count": (
            len(case_ids) * len(tasks) * len(model_keys)
        ),
        "progress_csv": str(progress_paths[0]),
        "progress_jsonl": str(progress_paths[1]),
    }
    metadata_path = results_dir / "run_metadata.json"
    write_json_atomic(run_metadata, metadata_path)

    summary_rows = []
    fatal_error = None
    interrupted = False

    try:
        for model_key in model_keys:
            args._auto_fallback_to_chunked = False
            config = MODEL_REGISTRY[model_key]
            print(
                f"Loading {config['name']} ({config['model_id']})",
                flush=True,
            )

            model = None
            processor = None
            try:
                model, processor = load_model(
                    config,
                    args.quantization,
                    args.dtype,
                )
            except Exception as error:
                load_error = (
                    f"model_load_failed: {type(error).__name__}: {error}"
                )
                for case_id in case_ids:
                    for task in tasks:
                        row = {
                            "run_id": run_id,
                            "model_key": model_key,
                            "model_id": config["model_id"],
                            "task": task["name"],
                            "case_id": case_id,
                            "json_valid": False,
                            "schema_valid": False,
                            "evidence_references_valid": False,
                            "error": load_error,
                        }
                        summary_rows.append(row)
                        append_progress_row(row, progress_paths)

                print(
                    f"Model load failed for {model_key}; continuing.",
                    flush=True,
                )
                model = None
                processor = None
                release_gpu_memory(torch)
                continue

            try:
                for case_id in case_ids:
                    snapshot_path = (
                        HARNESS_DIR / "snapshots" / f"{case_id}.json"
                    )
                    snapshot = load_json(snapshot_path)
                    snapshot_text = json.dumps(
                        snapshot,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    ground_truth_row = ground_truth_by_case.get(
                        case_id, {}
                    )

                    for task in tasks:
                        prompt = None
                        raw_path = (
                            raw_dir
                            / f"{model_key}__{case_id}__{task['name']}.json"
                        )

                        try:
                            prompt = build_prompt(
                                task["template"],
                                snapshot,
                                task["schema"],
                                snapshot_text,
                            )

                            # Reset the RNG before each response so sampling
                            # runs can be reproduced case-by-case.
                            seed_everything(args.seed, torch)

                            metrics = generate_response(
                                model,
                                processor,
                                prompt,
                                args,
                            )
                            raw_text = metrics.pop("text")

                            parse_error = None
                            try:
                                parsed = extract_json(raw_text)
                                json_valid = True
                            except Exception as error:
                                parsed = None
                                json_valid = False
                                parse_error = (
                                    f"json_parse_error: "
                                    f"{type(error).__name__}: {error}"
                                )
                                if (
                                    metrics.get("generated_tokens", 0)
                                    >= args.max_new_tokens
                                ):
                                    parse_error += (
                                        f" | output hit max_new_tokens="
                                        f"{args.max_new_tokens} (truncated)"
                                    )

                            schema_errors = []
                            reference_errors = []
                            if parsed is not None:
                                schema_errors = validate_json_schema(
                                    parsed,
                                    task["schema"],
                                )
                                reference_errors = validate_response(
                                    parsed,
                                    snapshot,
                                    ground_truth_row,
                                )

                            schema_valid = (
                                parsed is not None and not schema_errors
                            )
                            evidence_valid = (
                                parsed is not None and not reference_errors
                            )

                            error_messages = []
                            if parse_error:
                                error_messages.append(parse_error)
                            error_messages.extend(
                                f"schema_error: {message}"
                                for message in schema_errors
                            )
                            error_messages.extend(reference_errors)

                            validation = {
                                "json_valid": json_valid,
                                "schema_valid": schema_valid,
                                "evidence_references_valid": evidence_valid,
                                "schema_errors": schema_errors,
                                "reference_errors": reference_errors,
                            }

                            raw_record = {
                                "run_id": run_id,
                                "model_key": model_key,
                                "model_id": config["model_id"],
                                "task": task["name"],
                                "case_id": case_id,
                                "prompt": prompt,
                                "prompt_sha256": sha256_text(prompt),
                                "raw_response": raw_text,
                                "parsed_response": parsed,
                                "validation": validation,
                                "metrics": metrics,
                                "timestamp": utc_now(),
                            }
                            write_json_atomic(raw_record, raw_path)

                            row = {
                                "run_id": run_id,
                                "model_key": model_key,
                                "model_id": config["model_id"],
                                "task": task["name"],
                                "case_id": case_id,
                                "json_valid": json_valid,
                                "schema_valid": schema_valid,
                                "evidence_references_valid": evidence_valid,
                                "latency_seconds": metrics["latency_seconds"],
                                "prompt_tokens": metrics["prompt_tokens"],
                                "generated_tokens": metrics["generated_tokens"],
                                "tokens_per_second": metrics["tokens_per_second"],
                                "peak_gpu_memory_bytes": metrics["peak_gpu_memory_bytes"],
                                "peak_gpu_memory_before_bytes": metrics["peak_gpu_memory_before_bytes"],
                                "prefill_mode_used": metrics["prefill_mode_used"],
                                "prefill_chunks": metrics["prefill_chunks"],
                                "prefill_chunk_size": metrics["prefill_chunk_size"],
                                "error": "; ".join(error_messages),
                            }

                        except Exception as error:
                            error_text = (
                                f"generation_error: "
                                f"{type(error).__name__}: {error}"
                            )
                            row = {
                                "run_id": run_id,
                                "model_key": model_key,
                                "model_id": config["model_id"],
                                "task": task["name"],
                                "case_id": case_id,
                                "json_valid": False,
                                "schema_valid": False,
                                "evidence_references_valid": False,
                                "error": error_text,
                            }
                            error_record = {
                                "run_id": run_id,
                                "model_key": model_key,
                                "model_id": config["model_id"],
                                "task": task["name"],
                                "case_id": case_id,
                                "prompt": prompt,
                                "prompt_sha256": (
                                    sha256_text(prompt)
                                    if prompt is not None else None
                                ),
                                "error": error_text,
                                "timestamp": utc_now(),
                            }
                            write_json_atomic(error_record, raw_path)

                        summary_rows.append(row)
                        append_progress_row(row, progress_paths)

                        print(
                            f"[{len(summary_rows)}/"
                            f"{run_metadata['expected_response_count']}] "
                            f"{model_key} | {case_id} | {task['name']} | "
                            f"JSON={row.get('json_valid')} "
                            f"Schema={row.get('schema_valid')} "
                            f"Refs={row.get('evidence_references_valid')}",
                            flush=True,
                        )
            finally:
                # Clear the caller's references before garbage collection.
                model = None
                processor = None
                release_gpu_memory(torch)

    except KeyboardInterrupt:
        interrupted = True
        print("Benchmark interrupted. Saving completed responses.", flush=True)
    except Exception as error:
        fatal_error = (
            f"{type(error).__name__}: {error}"
        )
        print(f"Benchmark stopped: {fatal_error}", flush=True)
    finally:
        csv_path, json_path = write_final_results(
            summary_rows,
            results_dir,
        )

        error_count = sum(
            1 for row in summary_rows if row.get("error")
        )
        if interrupted:
            status = "interrupted"
        elif fatal_error:
            status = "failed"
        elif error_count:
            status = "completed_with_errors"
        else:
            status = "completed"

        run_metadata.update({
            "status": status,
            "finished_at": utc_now(),
            "response_count": len(summary_rows),
            "error_count": error_count,
            "fatal_error": fatal_error,
            "results_csv": str(csv_path),
            "results_json": str(json_path),
            "raw_responses": str(raw_dir),
        })
        write_json_atomic(run_metadata, metadata_path)

    print(json.dumps({
        "run_id": run_id,
        "status": run_metadata["status"],
        "results_csv": str(csv_path),
        "results_json": str(json_path),
        "progress_csv": str(progress_paths[0]),
        "progress_jsonl": str(progress_paths[1]),
        "run_metadata": str(metadata_path),
        "raw_responses": str(raw_dir),
        "response_count": len(summary_rows),
        "expected_response_count": run_metadata["expected_response_count"],
        "error_count": run_metadata["error_count"],
        "prefill_mode": args.prefill_mode,
        "prefill_chunk_size": args.prefill_chunk_size,
    }, indent=2))

    if interrupted:
        return 130
    if fatal_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
