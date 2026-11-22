"""Small function-calling dispatcher for FAA agent tools.

Each registered function has a name, purpose, typed parameter descriptions,
and a callable handler, matching the function-tool interface described in
Section 3.2.2 of the FAA paper.
"""


class FunctionCallingTool:
    def __init__(self):
        self._functions = {}

    def register(self, name, description, parameters, handler):
        if not name or not callable(handler):
            raise ValueError("A function name and callable handler are required.")
        if name in self._functions:
            raise ValueError(f"Function already registered: {name}")
        if not isinstance(parameters, dict):
            raise TypeError("Function parameters must be a dictionary schema.")
        self._functions[name] = {
            "description": description,
            "parameters": parameters,
            "handler": handler,
        }

    def definitions(self):
        """Return the registered function definitions for inspection/logging."""
        return {
            name: {
                "description": item["description"],
                "parameters": item["parameters"],
            }
            for name, item in self._functions.items()
        }

    def call(self, name, arguments):
        if name not in self._functions:
            raise ValueError(f"Unknown FAA function: {name}")
        if not isinstance(arguments, dict):
            raise TypeError("Function arguments must be a dictionary.")

        definition = self._functions[name]
        schema = definition["parameters"]
        required = schema.get("required", [])
        missing = [key for key in required if key not in arguments]
        if missing:
            raise ValueError(f"Missing required arguments for {name}: {missing}")

        properties = schema.get("properties", {})
        unexpected = set(arguments) - set(properties)
        if unexpected:
            raise ValueError(f"Unexpected arguments for {name}: {sorted(unexpected)}")

        return definition["handler"](**arguments)
