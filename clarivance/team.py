"""The starter Clarivance team: a coordinator that delegates to specialists."""

from __future__ import annotations

from datetime import date
from typing import Any

from .agent import Agent, EventHandler
from .tools import tool

WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


@tool
def current_date() -> str:
    """Return today's date in ISO format (YYYY-MM-DD)."""
    return date.today().isoformat()


def build_team(*, client: Any = None, on_event: EventHandler | None = None) -> dict[str, Agent]:
    """Create the researcher, writer and coordinator agents.

    Returns a dict keyed by agent name. The coordinator holds the other two
    as tools, so running it runs the whole team.
    """
    common = {"client": client, "on_event": on_event}

    researcher = Agent(
        "researcher",
        "You are Clarivance's research specialist. Investigate the question you are "
        "given using web search, and report back concise findings with the source "
        "URL for every claim. Say plainly when evidence is thin or conflicting.",
        description="Searches the web and returns sourced findings.",
        tools=[current_date],
        server_tools=[WEB_SEARCH],
        effort="medium",
        **common,
    )

    writer = Agent(
        "writer",
        "You are Clarivance's writing specialist. Turn the material you are given "
        "into clear, well-structured prose in the requested format. Keep every "
        "source citation you receive and do not add facts that are not in the material.",
        description="Turns notes and findings into polished written output.",
        effort="low",
        **common,
    )

    coordinator = Agent(
        "coordinator",
        "You are the Clarivance coordinator. Break the user's request into steps and "
        "delegate them to your specialist agents; you can call several at once when "
        "the steps are independent. Each specialist only sees the task text you give "
        "it, so include all the context it needs. Check their results, then give the "
        "user a final answer.",
        description="Plans the work and delegates to specialists.",
        tools=[researcher.as_tool(), writer.as_tool(), current_date],
        effort="high",
        **common,
    )

    return {a.name: a for a in (coordinator, researcher, writer)}
