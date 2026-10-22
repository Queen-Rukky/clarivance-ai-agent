"""The core Clarivance agent: a Claude tool-use loop with delegation support."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import anthropic

from .tools import Tool

DEFAULT_MODEL = "claude-opus-5-5"
# Server-side refusal fallback: if a safety classifier declines the request,
# the API re-runs it on Anthropic's recommended fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

EventHandler = Callable[[str, str, dict[str, Any]], None]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: Any) -> None:
        self.input_tokens += getattr(other, "input_tokens", 0) or 0
        self.output_tokens += getattr(other, "output_tokens", 0) or 0


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
    """

    def __init__(
        self,
        name: str,
        instructions: str,
        *,
        description: str = "",
        tools: Iterable[Tool] = (),
        server_tools: Iterable[dict[str, Any]] = (),
        model: str = DEFAULT_MODEL,
        effort: str = "medium",
        max_tokens: int = 16000,
        max_turns: int = 25,
        client: anthropic.Anthropic | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self.name = name
        self.instructions = instructions
        self.description = description or f"The {name} agent."
        self.tools = {t.name: t for t in tools}
        self.server_tools = list(server_tools)
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self._client = client
        self.on_event = on_event

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _emit(self, event: str, **data: Any) -> None:
        if self.on_event:
            self.on_event(self.name, event, data)

    def _tool_params(self) -> list[dict[str, Any]]:
        return [t.to_param() for t in self.tools.values()] + self.server_tools

    def _run_tool(self, block: Any) -> dict[str, Any]:
        self._emit("tool_call", tool=block.name, input=block.input)
        tool = self.tools.get(block.name)
        if tool is None:
            content, is_error = f"Error: unknown tool '{block.name}'", True
        else:
            content, is_error = tool.run(block.input or {})
        self._emit("tool_result", tool=block.name, is_error=is_error, content=content)
        result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": content}
        if is_error:
            result["is_error"] = True
        return result

    def run(self, task: str | list[dict[str, Any]]) -> AgentResult:
        """Run the agent on a task until it finishes, refuses, or hits a limit."""
        messages: list[dict[str, Any]] = (
            [{"role": "user", "content": task}] if isinstance(task, str) else list(task)
        )
        usage = Usage()
        self._emit("start", task=task if isinstance(task, str) else "<messages>")

        for turn in range(1, self.max_turns + 1):
            request: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": self.instructions,
                "messages": messages,
                "output_config": {"effort": self.effort},
                "betas": [FALLBACK_BETA],
                "fallbacks": "default",
            }
            tools = self._tool_params()
            if tools:
                request["tools"] = tools
            response = self.client.beta.messages.create(**request)
            usage.add(response.usage)
            # Append the full content (thinking, tool_use, etc.) unchanged so
            # the next request carries the model's own blocks back.
            messages.append({"role": "assistant", "content": response.content})
            stop = response.stop_reason

            if stop == "tool_use":
                calls = [b for b in response.content if b.type == "tool_use"]
                with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
                    results = list(pool.map(self._run_tool, calls))
                # All results go back in a single user message.
                messages.append({"role": "user", "content": results})
                continue
            if stop == "pause_turn":
                # A server tool (e.g. web search) paused mid-turn; resend to resume.
                continue

            text = "".join(b.text for b in response.content if b.type == "text")
            if stop == "refusal":
                details = getattr(response, "stop_details", None)
                self._emit("refusal", category=getattr(details, "category", None))
            self._emit("finish", stop_reason=stop, turns=turn)
            return AgentResult(text=text, stop_reason=stop, turns=turn, usage=usage, messages=messages)

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
