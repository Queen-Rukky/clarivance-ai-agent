"""Model providers for Clarivance agents.

Each backend speaks one API's message format. The agent loop only sees the
normalized `Step` a backend returns, so the same agents run on either the
Claude API or OpenRouter.

- `AnthropicBackend`: the Claude API through the official `anthropic` SDK.
- `OpenRouterBackend`: OpenRouter's OpenAI-compatible API, which includes
  free models (the default is the `openrouter/free` router).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent import Agent

ANTHROPIC_MODEL = "claude-opus-5-5"
OPENROUTER_MODEL = "openrouter/free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Server-side refusal fallback: if a safety classifier declines the request,
# the Claude API re-runs it on Anthropic's recommended fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    # Set when the model's arguments could not be parsed; reported back as an error.
    error: str | None = None


@dataclass
class Step:
    """One model response, normalized across providers.

    stop is one of: "end_turn", "tool_use", "pause_turn", "max_tokens", "refusal".
    """

    text: str
    stop: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    refusal_category: str | None = None


class AnthropicBackend:
    name = "anthropic"
    default_model = ANTHROPIC_MODEL

    def __init__(self, client: Any = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def start(self, agent: Agent, task: str) -> list[dict[str, Any]]:
        return [{"role": "user", "content": task}]

    def step(self, agent: Agent, messages: list[dict[str, Any]]) -> Step:
        request: dict[str, Any] = {
            "model": agent.model,
            "max_tokens": agent.max_tokens,
            "system": agent.instructions,
            "messages": messages,
            "output_config": {"effort": agent.effort},
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        tools = [t.to_param() for t in agent.tools.values()] + agent.server_tools
        if tools:
            request["tools"] = tools
        response = self.client.beta.messages.create(**request)
        # Append the full content (thinking, tool_use, etc.) unchanged so the
        # next request carries the model's own blocks back.
        messages.append({"role": "assistant", "content": response.content})
        details = getattr(response, "stop_details", None)
        return Step(
            text="".join(b.text for b in response.content if b.type == "text"),
            stop=response.stop_reason,
            tool_calls=[
                ToolCall(b.id, b.name, b.input or {}) for b in response.content if b.type == "tool_use"
            ],
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
            refusal_category=getattr(details, "category", None),
        )

    def add_tool_results(self, messages: list[dict[str, Any]], results: list[tuple[str, str, bool]]) -> None:
        content = []
        for call_id, text, is_error in results:
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id, "content": text}
            if is_error:
                block["is_error"] = True
            content.append(block)
        # All results go back in a single user message.
        messages.append({"role": "user", "content": content})


class OpenRouterBackend:
    name = "openrouter"
    default_model = OPENROUTER_MODEL

    def __init__(self, client: Any = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import openai

            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise RuntimeError("OPENROUTER_API_KEY is not set.")
            self._client = openai.OpenAI(
                api_key=key,
                base_url=OPENROUTER_BASE_URL,
                # Free models are rate limited; back off and retry on 429s.
                max_retries=5,
                default_headers={"X-Title": "Clarivance AI Agents"},
            )
        return self._client

    def start(self, agent: Agent, task: str) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": agent.instructions},
            {"role": "user", "content": task},
        ]

    def step(self, agent: Agent, messages: list[dict[str, Any]]) -> Step:
        request: dict[str, Any] = {
            "model": agent.model,
            "max_tokens": agent.max_tokens,
            "messages": messages,
        }
        if agent.tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in agent.tools.values()
            ]
        response = self.client.chat.completions.create(**request)
        if not response.choices:
            raise RuntimeError(f"OpenRouter returned no choices (model {agent.model}).")
        choice = response.choices[0]
        message = choice.message
        raw_calls = message.tool_calls or []

        assistant: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if raw_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
                }
                for c in raw_calls
            ]
        messages.append(assistant)

        calls = []
        for c in raw_calls:
            try:
                args = json.loads(c.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
                calls.append(ToolCall(c.id, c.function.name, args))
            except ValueError as exc:
                calls.append(ToolCall(c.id, c.function.name, {}, error=f"invalid tool arguments: {exc}"))

        # Some models return tool calls with finish_reason "stop"; trust the calls.
        if calls:
            stop = "tool_use"
        elif choice.finish_reason == "length":
            stop = "max_tokens"
        elif choice.finish_reason == "content_filter" or getattr(message, "refusal", None):
            stop = "refusal"
        else:
            stop = "end_turn"

        usage = response.usage
        return Step(
            text=message.content or getattr(message, "refusal", None) or "",
            stop=stop,
            tool_calls=calls,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    def add_tool_results(self, messages: list[dict[str, Any]], results: list[tuple[str, str, bool]]) -> None:
        for call_id, text, is_error in results:
            messages.append({"role": "tool", "tool_call_id": call_id, "content": text})


def default_provider() -> str:
    """Pick a provider from CLARIVANCE_PROVIDER, else from whichever API key is set."""
    explicit = os.environ.get("CLARIVANCE_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        return "openrouter"
    return "anthropic"


def make_backend(provider: str | None = None, client: Any = None) -> AnthropicBackend | OpenRouterBackend:
    provider = (provider or default_provider()).lower()
    if provider == "anthropic":
        return AnthropicBackend(client)
    if provider == "openrouter":
        return OpenRouterBackend(client)
    raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic' or 'openrouter'.")
