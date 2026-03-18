"""Budget Report tool — spending analysis by category, model, task, and timeline."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ouroboros.tools.registry import ToolContext, ToolEntry


def _load_events(drive_root: Path) -> list[dict]:
    """Load all llm_usage events from events.jsonl."""
    events_log = drive_root / "logs" / "events.jsonl"
    events = []
    if not events_log.exists():
        return events
    with events_log.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def _load_state(drive_root: Path) -> dict:
    """Load current state from state.json."""
    state_file = drive_root / "state" / "state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text())
    except Exception:
        return {}


def _budget_report(
    ctx: ToolContext,
    period: str = "session",
    group_by: str = "category",
    top_n: int = 10,
    include_timeline: bool = False,
) -> str:
    """Analyze and report on operational budget spending."""
    drive_root = Path(ctx.drive_root)
    state = _load_state(drive_root)
    events = _load_events(drive_root)

    # Determine time cutoff
    now = datetime.now(timezone.utc)
    cutoff = None
    period_label = "all time"

    if period == "session":
        # Use first worker_boot event as session start
        for ev in events:
            if ev.get("type") == "worker_boot":
                try:
                    cutoff = datetime.fromisoformat(ev["ts"])
                except Exception:
                    pass
                break
        period_label = "current session"
    elif period == "1h":
        from datetime import timedelta
        cutoff = now - timedelta(hours=1)
        period_label = "last 1 hour"
    elif period == "6h":
        from datetime import timedelta
        cutoff = now - timedelta(hours=6)
        period_label = "last 6 hours"
    elif period == "24h":
        from datetime import timedelta
        cutoff = now - timedelta(hours=24)
        period_label = "last 24 hours"
    elif period == "7d":
        from datetime import timedelta
        cutoff = now - timedelta(days=7)
        period_label = "last 7 days"
    # period == "all" -> no cutoff

    # Filter to llm_usage events within period
    usage_events = []
    for ev in events:
        if ev.get("type") != "llm_usage":
            continue
        if cutoff is not None:
            try:
                ts = datetime.fromisoformat(ev["ts"])
                if ts < cutoff:
                    continue
            except Exception:
                pass
        cost = ev.get("cost", 0) or 0
        usage_events.append({
            "ts": ev.get("ts", ""),
            "category": ev.get("category", "unknown") or "unknown",
            "model": ev.get("model", "unknown") or "unknown",
            "task_id": (ev.get("task_id", "") or "")[:12],
            "cost": float(cost),
            "prompt_tokens": ev.get("prompt_tokens", 0) or 0,
            "completion_tokens": ev.get("completion_tokens", 0) or 0,
        })

    total_cost = sum(e["cost"] for e in usage_events)
    total_calls = len(usage_events)
    total_prompt = sum(e["prompt_tokens"] for e in usage_events)
    total_completion = sum(e["completion_tokens"] for e in usage_events)

    # Budget figures from state
    budget_total = state.get("budget_total", 10.0) or 10.0
    spent_usd = state.get("spent_usd", 0.0) or 0.0
    remaining = max(0.0, budget_total - spent_usd)
    pct_used = round((spent_usd / budget_total * 100) if budget_total > 0 else 0, 1)
    pct_period = round((total_cost / budget_total * 100) if budget_total > 0 else 0, 1)

    # Group by chosen dimension
    grouped: Dict[str, Dict] = defaultdict(lambda: {"cost": 0.0, "calls": 0})
    for e in usage_events:
        if group_by == "model":
            key = e["model"]
        elif group_by == "task":
            key = e["task_id"] or "(background)"
        else:
            key = e["category"]
        grouped[key]["cost"] += e["cost"]
        grouped[key]["calls"] += 1

    breakdown = sorted(
        [
            {
                "name": k,
                "cost_usd": round(v["cost"], 6),
                "pct": round(v["cost"] / total_cost * 100 if total_cost > 0 else 0, 1),
                "calls": v["calls"],
            }
            for k, v in grouped.items()
        ],
        key=lambda x: x["cost_usd"],
        reverse=True,
    )[:top_n]

    # Format as human-readable text
    lines = []
    lines.append(f"## Budget Report — {period_label}")
    lines.append("")
    lines.append("### Overall Budget")
    lines.append(f"  Total budget:   ${budget_total:.2f}")
    lines.append(f"  Total spent:    ${spent_usd:.4f} ({pct_used}% used)")
    lines.append(f"  Remaining:      ${remaining:.4f}")
    lines.append("")
    lines.append(f"### Period ({period_label})")
    lines.append(f"  Cost:           ${total_cost:.6f} ({pct_period}% of budget)")
    lines.append(f"  LLM calls:      {total_calls}")
    lines.append(f"  Prompt tokens:  {total_prompt:,}")
    lines.append(f"  Completion tok: {total_completion:,}")
    if total_calls > 0:
        avg_cost = total_cost / total_calls
        lines.append(f"  Avg cost/call:  ${avg_cost:.6f}")
    lines.append("")
    lines.append(f"### Top {min(top_n, len(breakdown))} by {group_by}")
    if breakdown:
        for item in breakdown:
            bar = "█" * max(1, int(item["pct"] / 5))
            lines.append(f"  {item['name']:<30} ${item['cost_usd']:.6f}  {item['pct']:5.1f}%  {bar}  ({item['calls']} calls)")
    else:
        lines.append("  No data for this period.")

    if include_timeline:
        hourly: Dict[str, float] = defaultdict(float)
        for e in usage_events:
            try:
                ts = datetime.fromisoformat(e["ts"])
                hour_key = ts.strftime("%Y-%m-%d %H:00")
                hourly[hour_key] += e["cost"]
            except Exception:
                pass
        if hourly:
            lines.append("")
            lines.append("### Hourly Timeline")
            for h, c in sorted(hourly.items()):
                bar = "█" * max(1, int(c / total_cost * 30) if total_cost > 0 else 1)
                lines.append(f"  {h}   ${c:.6f}  {bar}")

    return "\n".join(lines)


def get_tools():
    return [
        ToolEntry(
            "budget_report",
            {
                "name": "budget_report",
                "description": (
                    "Analyze and report on operational budget spending. "
                    "Shows cost breakdown by category, model, or task. "
                    "Supports multiple time windows (session, 1h, 6h, 24h, 7d, all). "
                    "Optionally includes hourly spending timeline. "
                    "Useful for understanding where budget is going."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "enum": ["session", "1h", "6h", "24h", "7d", "all"],
                            "description": "Time window: session (default), 1h, 6h, 24h, 7d, all",
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["category", "model", "task"],
                            "description": "Group spending by: category (default), model, or task",
                        },
                        "top_n": {
                            "type": "integer",
                            "description": "Number of top items to show (default: 10)",
                        },
                        "include_timeline": {
                            "type": "boolean",
                            "description": "Include hourly spending timeline (default: false)",
                        },
                    },
                    "required": [],
                },
            },
            _budget_report,
        )
    ]
