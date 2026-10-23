"""Offline tests for the OpenRouter backend, using a scripted fake OpenAI client."""

from __future__ import annotations

from types import SimpleNamespace as NS

from clarivance import Agent, build_team, tool
from clarivance.backends import default_provider
from clarivance.web import html_to_text


def call(id_, name, arguments):
    return NS(id=id_, type="function", function=NS(name=name, arguments=arguments))


def completion(content=None, tool_calls=None, finish_reason="stop"):
    message = NS(content=content, tool_calls=tool_calls, refusal=None)
    return NS(
        choices=[NS(message=message, finish_reason=finish_reason)],
        usage=NS(prompt_tokens=7, completion_tokens=3),
    )


class FakeOpenAI:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def test_openrouter_tool_loop():
    client = FakeOpenAI(
        completion(tool_calls=[call("c1", "add", '{"a": 2, "b": 3}'), call("c2", "add", "{not json")]),
        completion(content="5"),
    )
    agent = Agent("a", "math", tools=[add], provider="openrouter", client=client)
    result = agent.run("2+3?")

    assert result.ok and result.text == "5" and result.turns == 2
    assert result.usage.input_tokens == 14
    first = client.requests[0]
    assert first["model"] == "openrouter/free"
    assert first["messages"][0] == {"role": "system", "content": "math"}
    assert first["tools"][0]["function"]["name"] == "add"
    tool_msgs = [m for m in client.requests[1]["messages"] if m["role"] == "tool"]
    assert tool_msgs[0] == {"role": "tool", "tool_call_id": "c1", "content": "5"}
    assert tool_msgs[1]["content"].startswith("Error: invalid tool arguments")
    assistant = client.requests[1]["messages"][2]
    assert [c["id"] for c in assistant["tool_calls"]] == ["c1", "c2"]


def test_openrouter_length_and_tool_calls_with_stop_reason():
    client = FakeOpenAI(
        # Some models report "stop" even when they called a tool.
        completion(tool_calls=[call("c1", "add", '{"a": 1, "b": 1}')], finish_reason="stop"),
        completion(content="partial", finish_reason="length"),
    )
    result = Agent("a", "x", tools=[add], provider="openrouter", client=client).run("go")
    assert result.stop_reason == "max_tokens" and result.text == "partial"


def test_provider_selection(monkeypatch):
    assert default_provider() == "anthropic"
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert default_provider() == "openrouter"
    monkeypatch.setenv("CLARIVANCE_MODEL", "some/model:free")
    assert Agent("a", "x", client=FakeOpenAI()).model == "some/model:free"
    monkeypatch.setenv("CLARIVANCE_PROVIDER", "anthropic")
    assert default_provider() == "anthropic"


def test_team_on_openrouter_uses_free_web_tools():
    team = build_team(provider="openrouter", client=FakeOpenAI())
    researcher = team["researcher"]
    assert researcher.server_tools == []
    assert {"web_search", "fetch_page", "current_date"} <= set(researcher.tools)


def test_html_to_text():
    html = "<html><head><style>x{}</style></head><body><nav>menu</nav><h1>Title</h1><p>Body text</p><script>1</script></body></html>"
    assert html_to_text(html) == "Title\nBody text"
