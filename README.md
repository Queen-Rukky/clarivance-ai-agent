# Clarivance AI Agents

A small multi-agent framework in Python that runs on either the **Claude API** or
**OpenRouter** (including OpenRouter's free models, so you can use it without paying).

Each **agent** has its own instructions, tools and model settings. Any agent can be
turned into a **tool** for another agent, so teams are built by giving a coordinator
its specialists as tools. The coordinator can call several specialists at once.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Free: an OpenRouter key (openrouter.ai -> Keys). Uses the free `openrouter/free` model.
export OPENROUTER_API_KEY=sk-or-...
# Or paid: a Claude API key. If both are set, Claude is used unless you pass --provider.
# export ANTHROPIC_API_KEY=sk-ant-...

clarivance "Compare the three most popular open-source vector databases and write a one-page summary"
clarivance --agent researcher "What changed in the latest Python release?"
```

Choose a provider or model explicitly with `--provider openrouter|anthropic` and
`--model <id>` (or the `CLARIVANCE_PROVIDER` / `CLARIVANCE_MODEL` environment variables).
Free OpenRouter models are rate limited (roughly 50 requests a day without credit); a full
coordinator run can use 10-30 requests, while `--agent writer` uses one or two.

Agent activity (delegations, tool calls, errors) is logged to stderr; the final answer
goes to stdout. Use `-q` to hide the logs.

## Layout

| Path | What it does |
| --- | --- |
| `clarivance/agent.py` | `Agent`: the tool-use loop (runs tools in parallel, handles `pause_turn`, refusals and turn limits, tracks token usage) and `Agent.as_tool()` for delegation |
| `clarivance/backends.py` | Providers: the Claude API (`anthropic` SDK) and OpenRouter (OpenAI-compatible API) |
| `clarivance/web.py` | Free `web_search` (DuckDuckGo) and `fetch_page` tools, used when the provider has no hosted search |
| `clarivance/tools.py` | `Tool` and the `@tool` decorator, which builds a strict JSON schema from a function's type hints and docstring |
| `clarivance/team.py` | The starter team: `coordinator` → `researcher` (web search) and `writer` |
| `clarivance/__main__.py` | The `clarivance` command-line tool |
| `website/` | The Clarivance Ltd company website and its chat function (Netlify) |
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

`Agent` options: `provider` (`anthropic` or `openrouter`), `model` (default `claude-opus-5-5`
on Claude, `openrouter/free` on OpenRouter), `effort` (`low` … `max`, Claude only),
`max_tokens`, `max_turns`, `server_tools` (Anthropic-hosted tools such as web search),
`client` (inject your own SDK client), and `on_event` (a callback for logging).

On the Claude API, requests opt into server-side refusal fallback (`fallbacks: "default"`), so a request a
safety classifier declines is retried on Anthropic's recommended fallback model.

## Company website (Netlify)

`website/` is the Clarivance Ltd website: training tracks, freelance services, a contact form
(Netlify Forms) and a chat assistant. It deploys to Netlify using `netlify.toml` at the repo root.

- `website/public/` is served as-is (no build step).
- `website/netlify/functions/chat.mts` serves `/api/chat`. It adds the assistant's instructions,
  forces the free `openrouter/free` model and streams the answer back. It reads the key from the
  `OPENROUTER_API_KEY` environment variable set on Netlify, so the key is never in the site or repo.
- Contact form messages appear in Netlify under **Forms**; turn on email notifications there.

## Running on GitHub Actions

The **Run Clarivance agent** workflow (`.github/workflows/run-agent.yml`) runs the agents on GitHub.

1. Add an API key under **Settings → Secrets and variables → Actions** as a repository secret:
   `OPENROUTER_API_KEY` (free models) or `ANTHROPIC_API_KEY` (Claude).
2. Open the **Actions** tab, choose **Run Clarivance agent**, click **Run workflow**, and enter a task
   (optionally a model ID; leave it empty for the default).
3. The result appears on the run page, as a downloadable `result.md`, and (optionally) as a new issue.

To run a task on a schedule, uncomment the `schedule` block in the workflow and edit the default task.
The repository is public, so run pages and issues are visible to anyone.

## Tests

```bash
pytest
```
