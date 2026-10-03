"""Provider-friendly discovery schemas for operation-based tools.

The operation-specific Pydantic validators remain authoritative. The merged
input object lets providers that require a top-level object see every field,
including nested definitions, without losing the operation requirements.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def operation_schema(inputs: dict[str, type[BaseModel]]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    definitions: dict[str, Any] = {}
    requirements = []
    for operation, model in inputs.items():
        schema = model.model_json_schema()
        definitions.update(deepcopy(schema.get("$defs", {})))
        for key, value in schema.get("properties", {}).items():
            properties.setdefault(key, deepcopy(value))
        required = schema.get("required", [])
        requirements.append(
            f"{operation}: requires {', '.join(required) if required else 'no input fields'}"
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "$defs": definitions,
        "properties": {
            "operation": {"type": "string", "enum": list(inputs)},
            "job_id": {
                "type": ["string", "null"],
                "description": "Use the exact returned job_id after start; omit for discovery/start.",
            },
            "request_id": {"type": ["string", "null"]},
            "input": {
                "type": "object",
                "additionalProperties": False,
                "description": "; ".join(requirements)
                + ". Only send fields for the chosen operation.",
                "properties": properties,
            },
        },
        "required": ["operation"],
    }
