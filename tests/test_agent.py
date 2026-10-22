"""Offline tests for the agent loop, using a scripted fake Claude client."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Literal

from clarivance import Agent, build_team, tool


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def response(content, stop_reason, **extra):
    return NS(content=content, stop_reason=stop_reason, usage=NS(input_tokens=10, output_tokens=5), **extra)


class FakeClient:
    """Returns scripted responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        # Snapshot messages: the agent keeps appending to the same list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@tool
def add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return a + b


def test_tool_schema_from_signature():
    @tool
    def search(query: str, limit: int = 5, mode: Literal["fast", "deep"] = "fast", tags: list[str] | None = None) -> str:
        """Search things.

        Args:
            query: What to look for.
        """
        return query

    s = search.input_schema
    assert search.description == "Search things."
    assert s["required"] == ["query", "limit", "mode", "tags"]
    assert s["additionalProperties"] is False
    assert s["properties"]["query"] == {"type": "string", "description": "What to look for."}
    assert s["properties"]["limit"]["type"] == ["integer", "null"]
    assert s["properties"]["mode"]["enum"] == ["fast", "deep"]
    assert s["properties"]["tags"]["items"] == {"type": "string"}
    # Nulls fall back to Python defaults.
    assert search.run({"query": "x", "limit": None, "mode": None, "tags": None}) == ("x", False)


def test_simple_answer():
    client = FakeClient(response([text("hello")], "end_turn"))
    result = Agent("a", "be nice", client=client).run("hi")
    assert result.ok and result.text == "hello" and result.turns == 1
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default"
    assert req["output_config"] == {"effort": "medium"}
    assert "tools" not in req


def test_tool_loop_sends_results_back():
    client = FakeClient(
        response([tool_use("t1", "add", {"a": 2, "b": 3}), tool_use("t2", "add", {"a": 1})], "tool_use"),
        response([text("5")], "end_turn"),
    )
    result = Agent("a", "math", tools=[add], client=client).run("2+3?")
    assert result.text == "5" and result.turns == 2
    assert result.usage.input_tokens == 20
    results = client.requests[1]["messages"][-1]["content"]
    assert results[0] == {"type": "tool_result", "tool_use_id": "t1", "content": "5"}
    assert results[1]["is_error"] and "missing required" in results[1]["content"]


def test_unknown_tool_and_exceptions_become_errors():
    @tool
    def boom() -> str:
        """Always fails."""
        raise ValueError("nope")

    client = FakeClient(
        response([tool_use("t1", "boom", {}), tool_use("t2", "ghost", {})], "tool_use"),
        response([text("ok")], "end_turn"),
    )
    Agent("a", "x", tools=[boom], client=client).run("go")
    r1, r2 = client.requests[1]["messages"][-1]["content"]
    assert r1["is_error"] and "ValueError: nope" in r1["content"]
    assert r2["is_error"] and "unknown tool" in r2["content"]


def test_pause_turn_resumes_and_refusal_stops():
    client = FakeClient(
        response([text("searching")], "pause_turn"),
        response([], "refusal", stop_details=NS(category="cyber")),
    )
    events = []
    agent = Agent("a", "x", client=client, on_event=lambda n, e, d: events.append(e))
    result = agent.run("q")
    assert result.stop_reason == "refusal" and not result.ok and result.turns == 2
    assert "refusal" in events


def test_max_turns():
    client = FakeClient(*[response([tool_use(f"t{i}", "add", {"a": 1, "b": 1})], "tool_use") for i in range(3)])
    result = Agent("a", "x", tools=[add], client=client, max_turns=3).run("loop")
    assert result.stop_reason == "max_turns"


def test_delegation_between_agents():
    specialist_client = FakeClient(response([text("specialist answer")], "end_turn"))
    specialist = Agent("helper", "help", description="Helps.", client=specialist_client)
    boss_client = FakeClient(
        response([tool_use("t1", "ask_helper", {"task": "do it"})], "tool_use"),
        response([text("done: specialist answer")], "end_turn"),
    )
    boss = Agent("boss", "lead", tools=[specialist.as_tool()], client=boss_client)
    result = boss.run("task")
    assert result.text == "done: specialist answer"
    assert specialist_client.requests[0]["messages"] == [{"role": "user", "content": "do it"}]
    assert boss_client.requests[1]["messages"][-1]["content"][0]["content"] == "specialist answer"


def test_failed_delegation_is_reported_as_error():
    specialist = Agent("helper", "help", client=FakeClient(response([], "refusal")))
    boss_client = FakeClient(
        response([tool_use("t1", "ask_helper", {"task": "x"})], "tool_use"),
        response([text("ok")], "end_turn"),
    )
    Agent("boss", "lead", tools=[specialist.as_tool()], client=boss_client).run("task")
    result = boss_client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "refusal" in result["content"]


def test_build_team_wiring():
    team = build_team(client=FakeClient())
    assert set(team) == {"coordinator", "researcher", "writer"}
    assert {"ask_researcher", "ask_writer", "current_date"} <= set(team["coordinator"].tools)
    assert team["researcher"].server_tools[0]["type"] == "web_search_20260209"
