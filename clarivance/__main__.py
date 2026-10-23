"""Command-line entry point: `python -m clarivance "your task"`."""

from __future__ import annotations

import argparse
import sys
from typing import Any

import anthropic
import openai

from .team import build_team


def _log(agent: str, event: str, data: dict[str, Any]) -> None:
    if event == "tool_call":
        detail = str(data["input"])
        print(f"[{agent}] -> {data['tool']} {detail[:200]}", file=sys.stderr)
    elif event == "tool_result" and data["is_error"]:
        print(f"[{agent}] !! {data['tool']} failed: {data['content'][:200]}", file=sys.stderr)
    elif event == "finish":
        print(f"[{agent}] done ({data['stop_reason']}, {data['turns']} turns)", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clarivance", description="Run a Clarivance agent.")
    parser.add_argument("task", help="What you want the agents to do.")
    parser.add_argument(
        "--agent",
        default="coordinator",
        choices=["coordinator", "researcher", "writer"],
        help="Which agent to run (default: coordinator, which delegates to the others).",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openrouter"],
        help="Model provider (default: CLARIVANCE_PROVIDER, else whichever API key is set).",
    )
    parser.add_argument("--model", help="Model ID (default: CLARIVANCE_MODEL, else the provider's default).")
    parser.add_argument("-q", "--quiet", action="store_true", help="Hide agent activity logs.")
    args = parser.parse_args(argv)

    team = build_team(provider=args.provider, model=args.model, on_event=None if args.quiet else _log)
    agent = team[args.agent]
    if not args.quiet:
        print(f"[clarivance] provider={agent.provider} model={agent.model}", file=sys.stderr)
    try:
        result = agent.run(args.task)
    except (anthropic.AuthenticationError, openai.AuthenticationError):
        print(f"Authentication failed for {agent.provider}: check your API key.", file=sys.stderr)
        return 2
    except (anthropic.RateLimitError, openai.RateLimitError):
        print(f"{agent.provider} rate limit reached (free models have daily limits). Try again later.", file=sys.stderr)
        return 2
    except (anthropic.APIConnectionError, openai.APIConnectionError) as exc:
        print(f"Could not reach {agent.provider}: {exc}", file=sys.stderr)
        return 2
    except (anthropic.APIStatusError, openai.APIStatusError) as exc:
        print(f"{agent.provider} API error {exc.status_code}: {exc.message}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(result.text)
    print(
        f"\n[{result.stop_reason}] {result.usage.input_tokens} input / "
        f"{result.usage.output_tokens} output tokens (top-level agent only)",
        file=sys.stderr,
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
