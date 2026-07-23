from __future__ import annotations
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from agent.decision import RebalanceDecision

_IN_MEMORY_LEDGER: list[dict] = []


def _make_entry(
    decision: RebalanceDecision,
    *,
    status: str,
    tx_hash: Optional[str] = None,
    balance_before: Optional[float] = None,
    balance_after: Optional[float] = None,
    error: Optional[str] = None,
    gas_used: Optional[int] = None,
    explorer_url: Optional[str] = None,
) -> dict:
    return {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "decision_timestamp": decision.timestamp,
        "action": decision.action,
        "pool": decision.pool,
        "amount_usdc": decision.amount_usdc,
        "percent_of_capital": decision.percent_of_capital,
        "reason": decision.reason,
        "inputs": decision.inputs,
        "status": status,
        "tx_hash": tx_hash,
        "explorer_url": explorer_url,
        "balance_before_usdc": balance_before,
        "balance_after_usdc": balance_after,
        "gas_used": gas_used,
        "error": error,
    }


def append_entry(
    decision: RebalanceDecision,
    *,
    status: str,
    tx_hash: Optional[str] = None,
    balance_before: Optional[float] = None,
    balance_after: Optional[float] = None,
    error: Optional[str] = None,
    gas_used: Optional[int] = None,
    explorer_url: Optional[str] = None,
    ledger_path: Optional[str] = None,
) -> dict:
    entry = _make_entry(
        decision,
        status=status,
        tx_hash=tx_hash,
        balance_before=balance_before,
        balance_after=balance_after,
        error=error,
        gas_used=gas_used,
        explorer_url=explorer_url,
    )
    _IN_MEMORY_LEDGER.append(entry)
    return entry


def read_entries(ledger_path: Optional[str] = None) -> list[dict]:
    return list(_IN_MEMORY_LEDGER)


def print_ledger(ledger_path: Optional[str] = None) -> None:
    entries = read_entries(ledger_path)
    if not entries:
        print("  (ledger is empty)")
        return
    for i, e in enumerate(entries, 1):
        status_icon = {
            "executed": "[OK]",
            "failed": "[!!]",
            "skipped": "[--]",
        }.get(e.get("status", ""), "[??]")
        print(
            f"  {i:>3d}. {status_icon} {e.get('logged_at', '?')[:19]}  "
            f"{e.get('action', '?'):<20s}  "
            f"${e.get('amount_usdc', 0):>8,.2f}  "
            f"{e.get('pool', '?'):<15s}  "
            f"tx={e.get('tx_hash', 'n/a')}"
        )
        if e.get("error"):
            print(f"       Error: {e['error']}")


def main() -> None:
    print()
    print("===================================================")
    print("  LiquidShift -- Ledger Contents")
    print("===================================================")
    print()
    print_ledger()
    print()


if __name__ == "__main__":
    main()
