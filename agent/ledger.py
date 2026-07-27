from __future__ import annotations
import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from agent.decision import RebalanceDecision

_DEFAULT_LEDGER_PATH = str(Path(__file__).resolve().parent.parent / "data" / "ledger.json")

_ledger_lock = threading.Lock()
_IN_MEMORY_LEDGER: list[dict] = []
_LEDGER_LOADED = False


def _resolve_path(ledger_path: Optional[str] = None) -> str:
    return ledger_path or os.getenv("LEDGER_PATH", _DEFAULT_LEDGER_PATH)


def _ensure_loaded(ledger_path: Optional[str] = None) -> None:
    global _LEDGER_LOADED
    if _LEDGER_LOADED:
        return
    path = Path(_resolve_path(ledger_path))
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                _IN_MEMORY_LEDGER.extend(data)
                print(f"  [Ledger] Loaded {len(data)} entries from {path}")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [Ledger] Warning: could not load {path}: {exc}")
    _LEDGER_LOADED = True


def _flush_to_disk(ledger_path: Optional[str] = None) -> None:
    path = Path(_resolve_path(ledger_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_IN_MEMORY_LEDGER, f, indent=2, default=str)
        tmp.replace(path)
    except OSError as exc:
        print(f"  [Ledger] Warning: could not write {path}: {exc}")


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
    with _ledger_lock:
        _ensure_loaded(ledger_path)
        _IN_MEMORY_LEDGER.append(entry)
        _flush_to_disk(ledger_path)
    return entry


def read_entries(ledger_path: Optional[str] = None) -> list[dict]:
    with _ledger_lock:
        _ensure_loaded(ledger_path)
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

