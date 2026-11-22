import pytest

from app.tools.function_calling_tool import FunctionCallingTool


def test_registered_function_is_dispatched():
    tool = FunctionCallingTool()
    tool.register(
        name="image_to_text",
        description="Analyze chart",
        parameters={
            "type": "object",
            "properties": {"chart_path": {"type": "string"}},
            "required": ["chart_path"],
        },
        handler=lambda chart_path: f"analysed:{chart_path}",
    )
    assert tool.call("image_to_text", {"chart_path": "chart.png"}) == "analysed:chart.png"


def test_function_tool_rejects_missing_arguments():
    tool = FunctionCallingTool()
    tool.register(
        name="image_to_text",
        description="Analyze chart",
        parameters={
            "type": "object",
            "properties": {"chart_path": {"type": "string"}},
            "required": ["chart_path"],
        },
        handler=lambda chart_path: chart_path,
    )
    with pytest.raises(ValueError, match="Missing required arguments"):
        tool.call("image_to_text", {})
