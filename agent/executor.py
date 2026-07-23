from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from web3 import Web3
from agent.config import TESTNET_MAX_TX_USDC
from agent.data_feed import POOLS
from agent.decision import RebalanceDecision
from agent.ledger import append_entry
from agent.circle_wallet import transfer_usdc, get_mode as circle_mode
from agent.wallet import NATIVE_DECIMALS, get_web3, read_usdc_balance

ARC_EXPLORER = "https://testnet.arcscan.app/tx/"
_POOL_NAME_TO_ENV: dict[str, str] = {p["name"]: p["env_key"] for p in POOLS}


@dataclass
class ExecutionResult:
    success: bool
    tx_hash: Optional[str] = None
    explorer_url: Optional[str] = None
    balance_before: Optional[float] = None
    balance_after: Optional[float] = None
    gas_used: Optional[int] = None
    error: Optional[str] = None
    status: str = "executed"
    transfer_id: Optional[str] = None
    transfer_mode: Optional[str] = None


def _resolve_pool_address(pool_name: str) -> Optional[str]:
    env_key = _POOL_NAME_TO_ENV.get(pool_name)
    if not env_key:
        return None
    addr = os.getenv(env_key)
    if not addr or not addr.strip():
        return None
    return Web3.to_checksum_address(addr.strip())


def execute_decision(
    decision: RebalanceDecision,
    w3: Web3,
    agent_wallet_id: str,
    agent_wallet_address: str,
) -> ExecutionResult:

    if decision.action == "hold":
        result = ExecutionResult(success=True, status="skipped")
        append_entry(decision, status="skipped")
        return result
    try:
        wallet_address = agent_wallet_address or ""
        balance_before = None
        if wallet_address:
            try:
                balance_before = float(read_usdc_balance(w3, wallet_address))
            except Exception:
                pass
        print(f"      [LIVE] Sending ${decision.amount_usdc:,.2f} USDC to {decision.pool}")
        if decision.action == "withdraw_to_idle":
            result = ExecutionResult(
                success=True,
                status="executed",
                balance_before=balance_before,
                transfer_mode="conceptual",
            )
            append_entry(
                decision,
                status="executed",
                balance_before=balance_before,
            )
            _log_result(decision, result)
            return result
        if decision.action == "move_to_pool":
            to_address = _resolve_pool_address(decision.pool)
            if not to_address:
                raise ValueError(
                    f"No address configured for pool '{decision.pool}'. "
                    f"Set {_POOL_NAME_TO_ENV.get(decision.pool, '???')} in .env."
                )
            if not agent_wallet_id:
                raise ValueError("No agent wallet ID available. " "Ensure Circle credentials are configured in .env.")
            amount_usdc = min(decision.amount_usdc, TESTNET_MAX_TX_USDC)
            transfer_result = transfer_usdc(
                source_wallet_id=agent_wallet_id,
                destination_address=to_address,
                amount_usdc=amount_usdc,
            )
            tx_hash = transfer_result.get("tx_hash", "")
            explorer_url = (ARC_EXPLORER + tx_hash) if tx_hash else None
            balance_after = None
            if wallet_address:
                try:
                    balance_after = float(read_usdc_balance(w3, wallet_address))
                except Exception:
                    pass
            result = ExecutionResult(
                success=True,
                tx_hash=tx_hash or None,
                explorer_url=explorer_url,
                balance_before=balance_before,
                balance_after=balance_after,
                status="executed",
                transfer_id=transfer_result.get("transfer_id"),
                transfer_mode=transfer_result.get("mode"),
            )
            append_entry(
                decision,
                status="executed",
                tx_hash=tx_hash or None,
                balance_before=balance_before,
                balance_after=balance_after,
                explorer_url=explorer_url,
            )
            _log_result(decision, result)
            return result
        else:
            raise ValueError(f"Unknown action: {decision.action}")
    except Exception as exc:
        result = ExecutionResult(success=False, error=str(exc), status="failed")
        append_entry(decision, status="failed", error=str(exc))
        _log_result(decision, result)
        return result


def _log_result(decision: RebalanceDecision, result: ExecutionResult) -> None:
    icon = {
        "executed": "[OK]",
        "skipped": "[--]",
    }.get(result.status, "[??]")
    mode_tag = f" ({result.transfer_mode})" if result.transfer_mode else ""
    print(f"  {icon} {decision.action:<20s}  " f"${decision.amount_usdc:>8,.2f} -> {decision.pool}{mode_tag}")
    if result.tx_hash:
        print(f"       tx: {result.explorer_url or result.tx_hash}")
    if result.transfer_id:
        print(f"       circle transfer: {result.transfer_id}")
    if result.balance_before is not None:
        line = f"       balance: ${result.balance_before:,.6f}"
        if result.balance_after is not None:
            line += f" -> ${result.balance_after:,.6f}"
        print(line)
    if result.gas_used:
        print(f"       gas: {result.gas_used}")
    if result.error:
        print(f"       error: {result.error}")


def main() -> None:
    from agent.circle_wallet import create_agent_wallet

    print()
    print("===================================================")
    print("  LiquidShift -- Executor Manual Test (Circle)")
    print("===================================================")
    print(f"  Safety cap: ${TESTNET_MAX_TX_USDC:.2f} USDC per tx")
    print(f"  Circle mode: {circle_mode()}")
    print()
    agent_wallet = create_agent_wallet()
    wallet_id = agent_wallet["circle_wallet_id"]
    address = agent_wallet["circle_address"]
    w3 = get_web3()
    balance = float(read_usdc_balance(w3, address)) if address else 0.0
    print(f"  Wallet ID : {wallet_id}")
    print(f"  Address   : {address}")
    print(f"  Balance   : ${balance:,.6f} USDC")
    print()
    target_pool = None
    target_addr = None
    for pool_cfg in POOLS:
        addr = os.getenv(pool_cfg["env_key"])
        if addr and addr.strip():
            target_pool = pool_cfg["name"]
            target_addr = addr.strip()
            break
    if not target_pool:
        print("  [!] No pool addresses configured in .env. Cannot test.")
        sys.exit(1)
    print(f"  Target : {target_pool} ({target_addr})")
    print()
    test_amount = min(0.01, TESTNET_MAX_TX_USDC)
    decision = RebalanceDecision(
        timestamp=datetime.now(timezone.utc).isoformat(),
        action="move_to_pool",
        pool=target_pool,
        amount_usdc=test_amount,
        percent_of_capital=round(test_amount / max(balance, 0.01) * 100, 4),
        reason=f"Manual test: sending ${test_amount} to {target_pool}",
        inputs={
            "manual_test": True,
            "wallet_id": wallet_id,
            "target": target_addr,
        },
    )
    print(f"  Sending ${test_amount:.6f} USDC to {target_pool}...")
    print()
    result = execute_decision(
        decision,
        w3=w3,
        agent_wallet_id=wallet_id,
        agent_wallet_address=address,
    )
    print()
    if result.success:
        print(f"  Test PASSED -- transfer {result.transfer_mode or 'completed'}.")
        if result.explorer_url:
            print(f"  Verify: {result.explorer_url}")
    else:
        print(f"  Test FAILED -- {result.error}")
    print()
    from agent.ledger import print_ledger

    print("--- Ledger ---")
    print_ledger()
    print()


if __name__ == "__main__":
    main()
