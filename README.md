# Clarivance AI Agents

A small multi-agent framework built on the Claude API (Python, official `anthropic` SDK).

Each **agent** has its own instructions, tools and model settings. Any agent can be
turned into a **tool** for another agent, so teams are built by giving a coordinator
its specialists as tools. The coordinator can call several specialists at once.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
export ANTHROPIC_API_KEY=sk-ant-...

clarivance "Compare the three most popular open-source vector databases and write a one-page summary"
clarivance --agent researcher "What changed in the latest Python release?"
```

Agent activity (delegations, tool calls, errors) is logged to stderr; the final answer
goes to stdout. Use `-q` to hide the logs.

## Layout

| Path | What it does |
| --- | --- |
| `clarivance/agent.py` | `Agent`: the tool-use loop (runs tools in parallel, handles `pause_turn`, refusals and turn limits, tracks token usage) and `Agent.as_tool()` for delegation |
| `clarivance/tools.py` | `Tool` and the `@tool` decorator, which builds a strict JSON schema from a function's type hints and docstring |
| `clarivance/team.py` | The starter team: `coordinator` → `researcher` (web search) and `writer` |
| `clarivance/__main__.py` | The `clarivance` command-line tool |
| `tests/` | Offline tests using a scripted fake client (no API key needed) |

## Building your own agents

```python
from clarivance import Agent, tool

@tool
def lookup_customer(email: str) -> dict:
    """Find a customer record.

    Args:
        email: The customer's email address.
    """
    return {"email": email, "plan": "pro"}

support = Agent(
    "support",
    "You answer customer questions. Look up the customer before answering.",
    description="Answers customer account questions.",
    tools=[lookup_customer],
)

lead = Agent("lead", "Route each request to the right specialist.", tools=[support.as_tool()])
print(lead.run("What plan is jane@example.com on?").text)
```

`Agent` options: `model` (default `claude-opus-5-5`), `effort` (`low` … `max`),
`max_tokens`, `max_turns`, `server_tools` (Anthropic-hosted tools such as web search),
`client` (inject your own `anthropic.Anthropic`), and `on_event` (a callback for logging).

Requests opt into server-side refusal fallback (`fallbacks: "default"`), so a request a
safety classifier declines is retried on Anthropic's recommended fallback model.

## Tests

```bash
pytest
```
