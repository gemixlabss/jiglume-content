"""Spending guard for paid Gemini API calls (shared by every AI tool).

The prepaid balance cannot be read with an API key, so each call's cost is
computed from the token usage the API returns (list prices, see
generate_ai.PRICE) and appended to ai/budget.json. A round has a hard limit;
`reserve(usd)` refuses work that would cross it (batch jobs reserve their
estimated cost before they are submitted).

    from budget import guard, record, remaining
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "ai" / "budget.json"


class BudgetExceeded(RuntimeError):
    pass


def _load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"round": None, "limitUsd": 0.0, "entries": []}


def _update(fn):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(str(LEDGER) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _load()
        out = fn(data)
        LEDGER.write_text(json.dumps(data, indent=1))
        return out


def start_round(name: str, limit_usd: float) -> None:
    def f(d):
        d["round"], d["limitUsd"] = name, limit_usd
        d.setdefault("history", []).append({"round": name, "limitUsd": limit_usd,
                                           "startedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        d["entries"] = []
    _update(f)


def spent() -> float:
    d = _load()
    return round(sum(e["usd"] for e in d["entries"]), 5)


def remaining() -> float:
    d = _load()
    return round(d["limitUsd"] - sum(e["usd"] for e in d["entries"]), 5)


def guard(estimate_usd: float) -> None:
    """Raises BudgetExceeded unless `estimate_usd` still fits this round."""
    if os.environ.get("JIGLUME_NO_BUDGET"):
        return
    if remaining() < estimate_usd:
        raise BudgetExceeded(f"budget: {remaining():.4f} $ left, {estimate_usd:.4f} $ needed")


def record(usd: float, what: str, kind: str = "actual") -> None:
    def f(d):
        d["entries"].append({"usd": round(usd, 6), "what": what, "kind": kind,
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _update(f)


def settle(what: str, actual_usd: float) -> None:
    """Replaces the reservation `what` by its actual cost."""
    def f(d):
        d["entries"] = [e for e in d["entries"] if not (e["what"] == what and e["kind"] == "reserved")]
        d["entries"].append({"usd": round(actual_usd, 6), "what": what, "kind": "actual",
                             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    _update(f)
