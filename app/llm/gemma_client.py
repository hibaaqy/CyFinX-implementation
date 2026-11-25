"""Gemma 4 client for Colab GPU inference with per-call performance telemetry."""

from pathlib import Path
from time import perf_counter

import torch
from transformers import AutoProcessor, AutoModelForMultimodalLM


def _gib(value):
    return round(float(value) / (1024 ** 3), 3)


class GemmaClient:
    def __init__(self, model, processor):
        self.model = model
        self.processor = processor
        self.call_metrics = []
        self.load_metrics = {}

    @classmethod
    def load(cls, model_id="google/gemma-4-E2B-it", dtype=None):
        if not torch.cuda.is_available():
            raise RuntimeError(
                "A CUDA GPU is required. Connect this notebook to a Colab GPU runtime."
            )

        load_started = perf_counter()
        model_dtype = dtype or torch.float16
        print(f"Loading Gemma processor: {model_id}")
        processor = AutoProcessor.from_pretrained(model_id)

        print("Loading Gemma multimodal model onto the available GPU...")
        model = AutoModelForMultimodalLM.from_pretrained(
            model_id,
            dtype=model_dtype,
            device_map="auto",
            low_cpu_mem_usage=True,
        )
        model.eval()
        client = cls(model, processor)
        client.load_metrics = {
            "model_id": model_id,
            "model_load_seconds": round(perf_counter() - load_started, 3),
            "gpu_memory_allocated_after_load_gib": _gib(torch.cuda.memory_allocated()),
            "gpu_memory_reserved_after_load_gib": _gib(torch.cuda.memory_reserved()),
        }
        print(
            "Gemma loaded successfully in "
            f"{client.load_metrics['model_load_seconds']:.1f}s."
        )
        return client

    def _generate_messages(self, messages, max_new_tokens=512, stage="unspecified"):
        started = perf_counter()
        input_tokens = 0
        output_tokens = 0
        status = "success"
        error_message = None
        peak_allocated = None
        peak_reserved = None

        try:
            inputs = self.processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                enable_thinking=False,
            ).to(self.model.device)

            input_tokens = int(inputs["input_ids"].shape[-1])
            with torch.inference_mode():
                output = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                )

            generated_tokens = output[0, input_tokens:]
            output_tokens = int(generated_tokens.numel())
            response = self.processor.decode(
                generated_tokens,
                skip_special_tokens=True,
            ).strip()

            if torch.cuda.is_available():
                peak_allocated = _gib(torch.cuda.memory_allocated())
                peak_reserved = _gib(torch.cuda.memory_reserved())
            return response

        except Exception as error:
            status = "error"
            error_message = f"{type(error).__name__}: {error}"
            raise

        finally:
            elapsed = perf_counter() - started
            self.call_metrics.append({
                "call_number": len(self.call_metrics) + 1,
                "stage": stage,
                "status": status,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_seconds": round(elapsed, 3),
                "output_tokens_per_second": (
                    round(output_tokens / elapsed, 3) if elapsed > 0 else 0.0
                ),
                "gpu_memory_allocated_after_call_gib": peak_allocated,
                "gpu_memory_reserved_after_call_gib": peak_reserved,
                "error": error_message,
            })

    def generate(self, prompt, max_new_tokens=512):
        """Generate text without an explicit stage label."""
        return self.generate_with_stage(
            stage="unspecified", prompt=prompt, max_new_tokens=max_new_tokens
        )

    def generate_with_stage(self, stage, prompt, max_new_tokens=512):
        """Generate text and record its FAA component/stage."""
        messages = [{"role": "user", "content": prompt}]
        return self._generate_messages(messages, max_new_tokens, stage=stage)

    def generate_with_image(self, image_path, prompt, max_new_tokens=512):
        """Generate a response grounded in a local chart image."""
        return self.generate_image_with_stage(
            stage="Vision Agent",
            image_path=image_path,
            prompt=prompt,
            max_new_tokens=max_new_tokens,
        )

    def generate_image_with_stage(
        self, stage, image_path, prompt, max_new_tokens=512
    ):
        """Generate a response from a chart image and record its stage."""
        image_path = Path(image_path).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Chart image not found: {image_path}")

        # Gemma 4's processor accepts image content before the text prompt.
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "url": str(image_path)},
                {"type": "text", "text": prompt},
            ],
        }]
        return self._generate_messages(messages, max_new_tokens, stage=stage)
