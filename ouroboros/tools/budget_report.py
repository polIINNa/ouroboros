"""Budget Report Tool — analyzes and reports on Ouroboros operational spending.

Reads from:
  - Drive/logs/events.jsonl  → llm_usage, task_done, task_received events
  - Drive/state/state.json   → current budget totals

Provides:
  1. Current budget status (spent / remaining / bar)
  2. Spending by category (task, consciousness, …)
  3. Spending by model
  4. Top 5 most expensive tasks
  5. Hourly spending timeline (last 24 h, ASCII sparkline)
  6. Efficiency metrics (cost/task, cache hit rate, …)
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

BUDGET_TOTAL_USD = 10.0  # Fixed budget cap


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ascii_bar(fraction: float, width: int = 20) -> str:
    """Return a filled/empty ASCII progress bar."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _sparkline(values: list[float]) -> str:
    """Convert a list of floats into a Unicode sparkline string."""
    sparks = "▁▂▃▄▅▆▇█"
    if not values or max(values) == 0:
        return "▁" * len(values) if values else "–"
    hi = max(values)
    return "".join(sparks[min(int(v / hi * (len(sparks) - 1)), len(sparks) - 1)] for v in values)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a .jsonl file; skip malformed lines silently."""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError as e:
        log.warning("budget_report: cannot read %s: %s", path, e)
    return rows


def _load_state(drive_root: Path) -> dict[str, Any]:
    """Load state.json; return empty dict on failure."""
    state_path = drive_root / "state" / "state.json"
    if not state_path.exists():
        return {}
    try:
        with state_path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("budget_report: cannot read state.json: %s", e)
        return {}


# ── Sections ──────────────────────────────────────────────────────────────────

def _section_status(state: dict, spent_from_events: float) -> str:
    """Section 1: current budget status."""
    spent = state.get("spent_usd", spent_from_events)
    remaining = max(0.0, BUDGET_TOTAL_USD - spent)
    pct_used = spent / BUDGET_TOTAL_USD
    bar = _ascii_bar(pct_used)

    lines = [
        "## 💰 Budget Status",
        f"  Total budget : ${BUDGET_TOTAL_USD:.2f}",
        f"  Spent        : ${spent:.4f}  ({pct_used*100:.1f}%)",
        f"  Remaining    : ${remaining:.4f}  ({(1-pct_used)*100:.1f}%)",
        f"  {bar} {pct_used*100:.1f}%",
    ]
    return "\n".join(lines)


def _section_by_category(usages: list[dict]) -> str:
    """Section 2: spending by category."""
    totals: dict[str, float] = defaultdict(float)
    for u in usages:
        cat = u.get("category") or "unknown"
        totals[cat] += u.get("cost", 0.0)

    if not totals:
        return "## 📊 Spending by Category\n  No data."

    grand = sum(totals.values())
    lines = ["## 📊 Spending by Category"]
    for cat, cost in sorted(totals.items(), key=lambda x: -x[1]):
        pct = cost / grand * 100 if grand else 0
        bar = _ascii_bar(cost / grand if grand else 0, width=12)
        lines.append(f"  {cat:<20} ${cost:.4f}  {pct:5.1f}%  {bar}")
    lines.append(f"  {'TOTAL':<20} ${grand:.4f}")
    return "\n".join(lines)


def _section_by_model(usages: list[dict]) -> str:
    """Section 3: spending by model."""
    totals: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "prompt": 0, "completion": 0, "cached": 0})
    for u in usages:
        model = u.get("model") or "unknown"
        totals[model]["cost"] += u.get("cost", 0.0)
        totals[model]["prompt"] += u.get("prompt_tokens", 0)
        totals[model]["completion"] += u.get("completion_tokens", 0)
        totals[model]["cached"] += u.get("cached_tokens", 0)

    if not totals:
        return "## 🤖 Spending by Model\n  No data."

    grand = sum(v["cost"] for v in totals.values())
    lines = ["## 🤖 Spending by Model"]
    for model, data in sorted(totals.items(), key=lambda x: -x[1]["cost"]):
        pct = data["cost"] / grand * 100 if grand else 0
        tok_str = f"prompt={data['prompt']:,}  compl={data['completion']:,}  cached={data['cached']:,}"
        lines.append(f"  {model}")
        lines.append(f"    ${data['cost']:.4f}  ({pct:.1f}%)  |  {tok_str}")
    return "\n".join(lines)


def _section_top_tasks(
    task_dones: list[dict],
    task_received: dict[str, str],
) -> str:
    """Section 4: top 5 most expensive tasks."""
    if not task_dones:
        return "## 🏋️ Top Expensive Tasks\n  No data."

    sorted_tasks = sorted(task_dones, key=lambda x: -x.get("cost_usd", 0.0))[:5]
    lines = ["## 🏋️ Top 5 Most Expensive Tasks"]
    for i, t in enumerate(sorted_tasks, 1):
        tid = t.get("task_id", "?")
        cost = t.get("cost_usd", 0.0)
        rounds = t.get("total_rounds", "?")
        preview = task_received.get(tid, "")[:60] or "(no preview)"
        lines.append(f"  {i}. [{tid[:8]}]  ${cost:.4f}  rounds={rounds}")
        lines.append(f"       \"{preview}\"")
    return "\n".join(lines)


def _section_timeline(usages: list[dict]) -> str:
    """Section 5: hourly spending timeline for the last 24 h."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    hourly: dict[int, float] = defaultdict(float)  # hour offset (0=oldest) → cost
    total_24h = 0.0

    for u in usages:
        ts_str = u.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if ts < cutoff:
            continue
        hour_idx = int((ts - cutoff).total_seconds() // 3600)
        hour_idx = min(hour_idx, 23)
        cost = u.get("cost", 0.0)
        hourly[hour_idx] += cost
        total_24h += cost

    values = [hourly.get(h, 0.0) for h in range(24)]
    spark = _sparkline(values)

    lines = [
        "## ⏱️ Spending Timeline (last 24 h)",
        f"  {spark}",
        "  (each character = 1 hour, oldest → newest)",
        f"  Total last 24h: ${total_24h:.4f}",
    ]
    # Show non-zero hours
    peak_h, peak_v = max(enumerate(values), key=lambda x: x[1])
    if peak_v > 0:
        peak_time = cutoff + timedelta(hours=peak_h)
        lines.append(f"  Peak hour: {peak_time.strftime('%H:00 UTC')}  (${peak_v:.4f})")
    return "\n".join(lines)


def _section_efficiency(usages: list[dict], task_dones: list[dict]) -> str:
    """Section 6: efficiency metrics."""
    if not usages:
        return "## ⚡ Efficiency Metrics\n  No data."

    total_cost = sum(u.get("cost", 0.0) for u in usages)
    total_rounds = len(usages)
    total_prompt = sum(u.get("prompt_tokens", 0) for u in usages)
    total_compl = sum(u.get("completion_tokens", 0) for u in usages)
    total_cached = sum(u.get("cached_tokens", 0) for u in usages)

    avg_per_round = total_cost / total_rounds if total_rounds else 0
    n_tasks = len(task_dones)
    avg_per_task = sum(t.get("cost_usd", 0) for t in task_dones) / n_tasks if n_tasks else 0

    cache_denom = total_prompt + total_cached
    cache_rate = total_cached / cache_denom * 100 if cache_denom else 0

    lines = [
        "## ⚡ Efficiency Metrics",
        f"  LLM rounds total      : {total_rounds:,}",
        f"  Avg cost / round      : ${avg_per_round:.5f}",
        f"  Tasks completed       : {n_tasks}",
        f"  Avg cost / task       : ${avg_per_task:.4f}",
        f"  Prompt tokens         : {total_prompt:,}",
        f"  Completion tokens     : {total_compl:,}",
        f"  Cached tokens         : {total_cached:,}",
        f"  Cache hit rate        : {cache_rate:.1f}%",
    ]
    return "\n".join(lines)


# ── Main entry ────────────────────────────────────────────────────────────────

def _budget_report(ctx: ToolContext) -> str:
    """Analyze and report on Ouroboros operational budget."""
    drive_root = Path(ctx.drive_root)

    # Load raw data
    events = _load_jsonl(drive_root / "logs" / "events.jsonl")
    state = _load_state(drive_root)

    # Separate by type
    usages = [e for e in events if e.get("type") == "llm_usage"]
    task_dones = [e for e in events if e.get("type") == "task_done"]
    task_received_events = [e for e in events if e.get("type") == "task_received"]

    # Build task_id → text preview map
    task_text: dict[str, str] = {}
    for e in task_received_events:
        task = e.get("task", {})
        tid = task.get("id", "")
        text = task.get("text", "")
        if tid:
            task_text[tid] = text

    spent_from_events = sum(u.get("cost", 0.0) for u in usages)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"# 📈 Ouroboros Budget Report\n_Generated: {generated_at}_\n"

    sections = [
        header,
        _section_status(state, spent_from_events),
        _section_by_category(usages),
        _section_by_model(usages),
        _section_top_tasks(task_dones, task_text),
        _section_timeline(usages),
        _section_efficiency(usages, task_dones),
    ]

    return "\n\n".join(sections)


# ── Registration ──────────────────────────────────────────────────────────────

def get_tools():
    return [
        ToolEntry("budget_report", {
            "name": "budget_report",
            "description": (
                "Analyze and report on Ouroboros operational budget. "
                "Shows: current spend/remaining, spending by category and model, "
                "top 5 most expensive tasks, hourly timeline (last 24h), "
                "and efficiency metrics (cache hit rate, cost per task/round)."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _budget_report),
    ]
