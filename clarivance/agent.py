"""The core Clarivance agent: a tool-use loop with delegation support."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .backends import ANTHROPIC_MODEL, ToolCall, make_backend
from .tools import Tool

DEFAULT_MODEL = ANTHROPIC_MODEL

EventHandler = Callable[[str, str, dict[str, Any]], None]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AgentResult:
    text: str
    stop_reason: str
    turns: int
    usage: Usage
    messages: list[dict[str, Any]] = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.stop_reason == "end_turn"


class Agent:
    """A named agent with its own instructions, tools and model settings.

    Agents can be handed to other agents via `as_tool()`, which is how
    Clarivance builds multi-agent teams: a coordinator delegates work to
    specialists by calling them like any other tool.

    `provider` is "anthropic" (Claude API) or "openrouter". When omitted it
    comes from CLARIVANCE_PROVIDER, or from whichever API key is set.
    `model` defaults to CLARIVANCE_MODEL, else the provider's default.
    """

    def __init__(
        self,
        name: str,
        instructions: str,
        *,
        description: str = "",
        tools: Iterable[Tool] = (),
        server_tools: Iterable[dict[str, Any]] = (),
        provider: str | None = None,
        model: str | None = None,
        effort: str = "medium",
        max_tokens: int = 16000,
        max_turns: int = 25,
        client: Any = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self.description = description or f"The {name} agent."
        self.tools = {t.name: t for t in tools}
        self.backend = make_backend(provider, client)
        # Anthropic-hosted tools (e.g. web search) only exist on the Claude API.
        self.server_tools = list(server_tools) if self.backend.name == "anthropic" else []
        self.model = model or os.environ.get("CLARIVANCE_MODEL") or self.backend.default_model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.on_event = on_event

    @property
    def provider(self) -> str:
        return self.backend.name

    def _emit(self, event: str, **data: Any) -> None:
        if self.on_event:
            self.on_event(self.name, event, data)

    def _run_tool(self, call: ToolCall) -> tuple[str, str, bool]:
        self._emit("tool_call", tool=call.name, input=call.input)
        tool = self.tools.get(call.name)
        if call.error:
            content, is_error = f"Error: {call.error}", True
        elif tool is None:
            content, is_error = f"Error: unknown tool '{call.name}'", True
        else:
            content, is_error = tool.run(call.input)
        self._emit("tool_result", tool=call.name, is_error=is_error, content=content)
        return call.id, content, is_error

    def run(self, task: str) -> AgentResult:
        """Run the agent on a task until it finishes, refuses, or hits a limit."""
        messages = self.backend.start(self, task)
        usage = Usage()
        self._emit("start", task=task)

        for turn in range(1, self.max_turns + 1):
            step = self.backend.step(self, messages)
            usage.input_tokens += step.input_tokens
            usage.output_tokens += step.output_tokens

            if step.stop == "tool_use" and step.tool_calls:
                calls = step.tool_calls
                with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                    results = list(pool.map(self._run_tool, calls))
                self.backend.add_tool_results(messages, results)
                continue
            if step.stop == "pause_turn":
                # A server tool (e.g. web search) paused mid-turn; resend to resume.
                continue

            if step.stop == "refusal":
                self._emit("refusal", category=step.refusal_category)
            self._emit("finish", stop_reason=step.stop, turns=turn)
            return AgentResult(text=step.text, stop_reason=step.stop, turns=turn, usage=usage, messages=messages)

        self._emit("finish", stop_reason="max_turns", turns=self.max_turns)
        return AgentResult(
            text="", stop_reason="max_turns", turns=self.max_turns, usage=usage, messages=messages
        )

    def as_tool(self, name: str | None = None) -> Tool:
        """Expose this agent as a tool another agent can delegate to."""

        def delegate(task: str) -> str:
            result = self.run(task)
            if result.ok:
                return result.text
            raise RuntimeError(
                f"{self.name} stopped with '{result.stop_reason}'"
                + (f"; partial output: {result.text}" if result.text else "")
            )

        return Tool(
            name=name or f"ask_{self.name}",
            description=(
                f"Delegate a task to the {self.name} agent. {self.description} "
                "Give it a complete, self-contained task description: it cannot see "
                "this conversation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The full task for the agent."}
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            fn=delegate,
        )
