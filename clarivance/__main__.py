"""Command-line entry point: `python -m clarivance "your task"`."""

from __future__ import annotations

import argparse
import sys
from typing import Any

import anthropic

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
    parser.add_argument("-q", "--quiet", action="store_true", help="Hide agent activity logs.")
    args = parser.parse_args(argv)

    team = build_team(on_event=None if args.quiet else _log)
    try:
        result = team[args.agent].run(args.task)
    except anthropic.AuthenticationError:
        print("Authentication failed: set ANTHROPIC_API_KEY or run `ant auth login`.", file=sys.stderr)
        return 2
    except anthropic.APIConnectionError as exc:
        print(f"Could not reach the Claude API: {exc}", file=sys.stderr)
        return 2
    except anthropic.APIStatusError as exc:
        print(f"Claude API error {exc.status_code}: {exc.message}", file=sys.stderr)
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
