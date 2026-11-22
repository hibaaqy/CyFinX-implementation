import pytest

from app.utils.model_output import extract_json_object, extract_python_code


def test_extract_json_from_fenced_response():
    assert extract_json_object('```json\n{"decision":"legitimate"}\n```') == {
        "decision": "legitimate"
    }


def test_extract_python_from_fenced_response():
    assert extract_python_code("```python\nevidence_results = {}\n```") == "evidence_results = {}"


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        extract_json_object("No JSON here")
