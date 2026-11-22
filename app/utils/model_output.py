"""Small parsers for structured outputs returned by Gemma."""

import json
import re


def extract_json_object(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned an empty response.")

    cleaned = text.strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object found in model response:\n{text}")

    try:
        result = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as error:
        raise ValueError(f"Model returned invalid JSON: {error}\n{text}") from error

    if not isinstance(result, dict):
        raise ValueError("Expected the model to return a JSON object.")
    return result


def extract_python_code(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The model returned no Python code.")

    cleaned = text.strip()
    match = re.fullmatch(
        r"```(?:python|py)?\s*(.*?)\s*```",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        cleaned = match.group(1).strip()
    elif cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[-1].strip() == "```":
            cleaned = "\n".join(lines[1:-1]).strip()
    return cleaned
