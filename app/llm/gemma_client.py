"""Gemma 4 client for Colab GPU inference (text and image inputs)."""

from pathlib import Path

import torch
from transformers import AutoProcessor, AutoModelForMultimodalLM


class GemmaClient:
    def __init__(self, model, processor):
        self.model = model
        self.processor = processor

    @classmethod
    def load(cls, model_id="google/gemma-4-E2B-it", dtype=None):
        if not torch.cuda.is_available():
            raise RuntimeError(
                "A CUDA GPU is required. Connect this notebook to a Colab GPU runtime."
            )

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
        print("Gemma loaded successfully.")
        return cls(model, processor)

    def _generate_messages(self, messages, max_new_tokens=512):
        inputs = self.processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        ).to(self.model.device)

        input_length = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        generated_tokens = output[0, input_length:]
        return self.processor.decode(
            generated_tokens,
            skip_special_tokens=True,
        ).strip()

    def generate(self, prompt, max_new_tokens=512):
        """Generate a text-only response."""
        messages = [{"role": "user", "content": prompt}]
        return self._generate_messages(messages, max_new_tokens)

    def generate_with_image(self, image_path, prompt, max_new_tokens=512):
        """Generate a response grounded in a local chart image."""
        image_path = Path(image_path).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Chart image not found: {image_path}")

        # Gemma 4's Transformers processor accepts image content before text.
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "url": str(image_path)},
                {"type": "text", "text": prompt},
            ],
        }]
        return self._generate_messages(messages, max_new_tokens)
