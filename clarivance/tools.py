"""Tool definitions for Clarivance agents.

A `Tool` pairs the JSON schema Claude sees with the Python function that runs
when Claude calls it. The `@tool` decorator builds the schema from the
function's signature and docstring so most tools need no hand-written schema.
"""

from __future__ import annotations

import inspect
import json
import types
import typing
from dataclasses import dataclass
from typing import Any, Callable

_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
}


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]

    def to_param(self) -> dict[str, Any]:
        """The tool definition sent to the Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "strict": True,
        }

    def run(self, tool_input: dict[str, Any]) -> tuple[str, bool]:
        """Run the tool. Returns (content, is_error); exceptions become error results."""
        missing = [k for k in self.input_schema.get("required", []) if k not in tool_input]
        if missing:
            return f"Error: missing required argument(s): {', '.join(missing)}", True
        try:
            result = self.fn(**tool_input)
        except Exception as exc:  # report to Claude so it can recover
            return f"Error: {type(exc).__name__}: {exc}", True
        if isinstance(result, str):
            return result, False
        return json.dumps(result, default=str), False


def _schema_for(annotation: Any) -> dict[str, Any]:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        non_null = [a for a in args if a is not type(None)]
        if len(non_null) == 1:
            return _schema_for(non_null[0])
    if origin is typing.Literal:
        return {"type": _JSON_TYPES.get(type(args[0]), "string"), "enum": list(args)}
    if origin in (list, tuple, set):
        item = _schema_for(args[0]) if args else {}
        return {"type": "array", "items": item}
    if annotation in _JSON_TYPES:
        return {"type": _JSON_TYPES[annotation]}
    return {"type": "string"}


def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Split a docstring into its summary and an `Args:` section mapping."""
    summary_lines: list[str] = []
    params: dict[str, str] = {}
    in_args = False
    current = None
    for raw in inspect.cleandoc(doc).splitlines():
        line = raw.strip()
        if line.lower() in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args:
            if not line:
                continue
            name, sep, desc = line.partition(":")
            if sep and " " not in name.strip():
                current = name.strip()
                params[current] = desc.strip()
            elif current:
                params[current] += " " + line
        else:
            summary_lines.append(line)
    return " ".join(l for l in summary_lines if l).strip(), params


def tool(fn: Callable[..., Any] | None = None, *, name: str | None = None, description: str | None = None):
    """Turn a typed Python function into a `Tool`.

    Usage:
        @tool
        def add(a: int, b: int) -> int:
            '''Add two numbers.

            Args:
                a: First number.
                b: Second number.
            '''
            return a + b
    """

    def wrap(f: Callable[..., Any]) -> Tool:
        summary, param_docs = _parse_docstring(f.__doc__ or "")
        hints = typing.get_type_hints(f)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, param in inspect.signature(f).parameters.items():
            prop = _schema_for(hints.get(pname, str))
            if pname in param_docs:
                prop["description"] = param_docs[pname]
            properties[pname] = prop
            # Strict tool use requires every property to be listed as required;
            # optional parameters are therefore expressed as nullable.
            required.append(pname)
            if param.default is not inspect.Parameter.empty:
                prop["type"] = [prop["type"], "null"] if isinstance(prop.get("type"), str) else prop.get("type")
        schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

        def call(**kwargs: Any) -> Any:
            # Drop explicit nulls so Python defaults apply.
            return f(**{k: v for k, v in kwargs.items() if v is not None})

        return Tool(
            name=name or f.__name__,
            description=description or summary or f.__name__,
            input_schema=schema,
            fn=call,
        )

    return wrap(fn) if fn is not None else wrap
