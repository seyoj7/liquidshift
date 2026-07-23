from __future__ import annotations
import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.data_feed import get_current_snapshots, POOLS, PoolSnapshot
from agent.decision import (
    AllocationState,
    DecisionEngine,
    apply_decisions,
)
from agent.executor import execute_decision
from agent.ledger import read_entries
from agent.wallet import get_web3, read_usdc_balance
from agent.circle_wallet import (
    create_agent_wallet,
    create_circle_wallet,
    get_circle_wallet_balance,
    get_mode as circle_mode,
)
from agent.config import (
    AGENT_LOOP_INTERVAL_S,
    MODEL_CAPITAL_USDC,
    DASHBOARD_PORT,
    TESTNET_MAX_TX_USDC,
)

LOOP_INTERVAL_S = AGENT_LOOP_INTERVAL_S
MODEL_CAPITAL = MODEL_CAPITAL_USDC
DASHBOARD_PORT = DASHBOARD_PORT
FEE_RATE = 0.003
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"


class AgentLoop:
    def __init__(self, *, interval_s: int = LOOP_INTERVAL_S):
        self.interval_s = interval_s
        self.w3 = get_web3()
        self.engine = DecisionEngine()
        self.agent_wallet_id = None
        self.wallet_address = None
        self.wallet_mode = None
        print("  No EVM wallet connected yet. Waiting for dashboard connection...")
        if self.wallet_address:
            balance = float(read_usdc_balance(self.w3, self.wallet_address))
        else:
            balance = 0.0
        pool_names = [p["name"] for p in POOLS]
        per_pool = MODEL_CAPITAL / max(len(pool_names), 1)
        self.state = AllocationState(
            idle_usdc=0.0,
            pool_allocations={name: per_pool for name in pool_names},
        )
        self.earnings_active = 0.0
        self.earnings_passive = 0.0
        self.earnings_history: list[dict] = [{"t": datetime.now(timezone.utc).isoformat(), "a": 0.0, "p": 0.0}]
        self.last_snapshots: list[PoolSnapshot] = []
        self.cycle_count = 0
        self.running = False
        self.is_started = False
        self.start_time: Optional[datetime] = None
        self.last_cycle_time: Optional[datetime] = None
        self.wallet_balance = balance
        self._lock = threading.Lock()

    def run(self) -> None:
        self.running = True
        print(f"\n  Agent loop thread started  interval={self.interval_s}s  " f"circle_mode={self.wallet_mode}")
        print(f"  Model capital : ${MODEL_CAPITAL:,.2f}")
        if self.wallet_address:
            print(f"  Wallet        : {self.wallet_address}")
            print(f"  Wallet ID     : {self.agent_wallet_id}")
            print(f"  Balance       : ${self.wallet_balance:,.6f}\n")
        else:
            print("  Wallet        : Not connected (connect via dashboard)\n")
        while self.running:
            if self.is_started:
                try:
                    self._run_cycle()
                except Exception as exc:
                    print(f"  [!!] Cycle error: {exc}")
            sleep_time = self.interval_s if self.is_started else 1
            for _ in range(sleep_time):
                if not self.running:
                    break
                time.sleep(1)
        print("  Agent loop stopped.\n")

    def stop(self) -> None:
        self.running = False

    def _run_cycle(self) -> None:
        now = datetime.now(timezone.utc)
        self.cycle_count += 1
        print(f"  --- Cycle {self.cycle_count} @ {now.strftime('%H:%M:%S UTC')} ---")
        with self._lock:
            if not self.agent_wallet_id:
                print("  Waiting for EVM wallet connection via dashboard...")
                return
        snapshots = get_current_snapshots(self.w3)
        with self._lock:
            self.last_snapshots = snapshots
        self._accrue_earnings(snapshots)
        decisions = self.engine.evaluate(snapshots, self.state, now=now)
        for d in decisions:
            if d.action != "hold":
                print(f"    >> {d.action}: ${d.amount_usdc:,.2f} -> {d.pool}")
                execute_decision(
                    d,
                    w3=self.w3,
                    agent_wallet_id=self.agent_wallet_id,
                    agent_wallet_address=self.wallet_address,
                )
        new_state = apply_decisions(self.state, decisions, now=now)
        with self._lock:
            self.state = new_state
            self.last_cycle_time = now
            if self.wallet_address:
                try:
                    self.wallet_balance = float(read_usdc_balance(self.w3, self.wallet_address))
                except Exception:
                    pass
        sources = {s.source for s in snapshots}
        print(
            f"    data={','.join(sorted(sources))}  "
            f"idle=${self.state.idle_usdc:,.0f}  "
            f"active=+${self.earnings_active:,.4f}  "
            f"passive=+${self.earnings_passive:,.4f}"
        )

    def update_active_wallet(self, circle_wallet_id: str, circle_address: str, mode: str):
        with self._lock:
            self.agent_wallet_id = circle_wallet_id
            self.wallet_address = circle_address
            self.wallet_mode = mode
            try:
                self.wallet_balance = float(read_usdc_balance(self.w3, self.wallet_address))
            except Exception:
                self.wallet_balance = 0.0
            print(f"  [AgentLoop] Switched active wallet to: {self.wallet_address} ({self.wallet_mode})")

    def _accrue_earnings(self, snapshots: list[PoolSnapshot]) -> None:
        num_pools = max(len(snapshots), 1)
        active_delta = 0.0
        passive_delta = 0.0
        time_fraction = self.interval_s / 3600.0
        for snap in snapshots:
            if snap.liquidity <= 0:
                continue
            alloc = self.state.pool_allocations.get(snap.pool, 0.0)
            if alloc > 0:
                active_delta += snap.volume_1h * FEE_RATE * (alloc / snap.liquidity) * time_fraction
            passive_alloc = MODEL_CAPITAL / num_pools
            passive_delta += snap.volume_1h * FEE_RATE * (passive_alloc / snap.liquidity) * time_fraction
        now = datetime.now(timezone.utc)
        with self._lock:
            self.earnings_active += active_delta
            self.earnings_passive += passive_delta
            self.earnings_history.append(
                {
                    "t": now.isoformat(),
                    "a": round(self.earnings_active, 4),
                    "p": round(self.earnings_passive, 4),
                }
            )

    def get_api_state(self) -> dict:
        with self._lock:
            ledger = read_entries()
            recent_ledger = ledger[-200:] if len(ledger) > 200 else ledger
            pool_cfgs = []
            for p in POOLS:
                addr = os.getenv(p["env_key"], "")
                pool_cfgs.append(
                    {
                        "name": p["name"],
                        "address": addr if addr else None,
                    }
                )
            return {
                "agent": {
                    "status": ("running" if self.is_started else ("waiting" if self.running else "stopped")),
                    "cycle": self.cycle_count,
                    "interval_s": self.interval_s,
                    "started": self.start_time.isoformat() if self.start_time else None,
                    "last_cycle": (self.last_cycle_time.isoformat() if self.last_cycle_time else None),
                    "model_capital": MODEL_CAPITAL,
                    "max_tx": TESTNET_MAX_TX_USDC,
                },
                "wallet": {
                    "address": self.wallet_address,
                    "balance": self.wallet_balance,
                    "circle_wallet_id": self.agent_wallet_id,
                    "mode": self.wallet_mode,
                },
                "allocation": {
                    "idle": round(self.state.idle_usdc, 2),
                    "pools": {k: round(v, 2) for k, v in self.state.pool_allocations.items() if v > 0},
                    "total": round(self.state.total_capital, 2),
                },
                "snapshots": [
                    {
                        "pool": s.pool,
                        "vol1h": s.volume_1h,
                        "vol24h": s.volume_24h_avg,
                        "liq": s.liquidity,
                        "src": s.source,
                        "vol": s.volatility,
                    }
                    for s in self.last_snapshots
                ],
                "earnings": {
                    "active": round(self.earnings_active, 4),
                    "passive": round(self.earnings_passive, 4),
                    "history": self.earnings_history[-200:],
                },
                "ledger": recent_ledger,
                "pools": pool_cfgs,
                "connected_wallets": len(_SESSION_WALLETS),
                "circle_mode": circle_mode(),
            }


_agent: Optional[AgentLoop] = None
_SESSION_WALLETS = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            self._json_response(_agent.get_api_state() if _agent else {})
        elif self.path == "/api/wallet/list":
            self._json_response({"wallets": list(_SESSION_WALLETS.values())})
        elif self.path in ("/", "/index.html"):
            self._file_response("index.html", "text/html")
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/wallet/connect":
            self._handle_wallet_connect()
        elif self.path == "/api/agent/start":
            self._handle_agent_start()
        elif self.path == "/api/agent/stop":
            self._handle_agent_stop()
        else:
            self.send_error(404)

    def _handle_agent_start(self):
        if not _agent.wallet_address:
            self._json_response({"error": "No wallet connected"}, status=400)
            return
        with _agent._lock:
            if not _agent.is_started:
                _agent.is_started = True
                _agent.start_time = datetime.now(timezone.utc)
                print("  [Agent] Started via dashboard.")
        self._json_response({"status": "started"})

    def _handle_agent_stop(self):
        with _agent._lock:
            if _agent.is_started:
                _agent.is_started = False
                print("  [Agent] Stopped/Paused via dashboard.")
        self._json_response({"status": "stopped"})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _handle_wallet_connect(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))
            evm_address = data.get("evm_address", "").strip()
            if not evm_address or not evm_address.startswith("0x"):
                self._json_response({"error": "Invalid EVM address"}, status=400)
                return
            try:
                from web3 import Web3

                evm_address = Web3.to_checksum_address(evm_address)
            except Exception:
                pass
            existing = _SESSION_WALLETS.get(evm_address)
            if existing:
                balance = get_circle_wallet_balance(existing["circle_wallet_id"])
                result = {
                    **existing,
                    "usdc_balance": balance,
                    "is_new": False,
                }
                _agent.update_active_wallet(
                    circle_wallet_id=result["circle_wallet_id"],
                    circle_address=result["circle_address"],
                    mode=result["mode"],
                )
                print(f"  [Wallet] Reconnected: {evm_address[:10]}... " f"-> {existing['circle_wallet_id'][:8]}...")
                self._json_response(result)
                return
            wallet_info = create_circle_wallet(evm_address)
            mapping = {
                "evm_address": evm_address,
                "circle_wallet_id": wallet_info["circle_wallet_id"],
                "circle_address": wallet_info["circle_address"],
                "blockchain": wallet_info["blockchain"],
                "mode": wallet_info["mode"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            _SESSION_WALLETS[evm_address] = mapping
            from agent.decision import RebalanceDecision
            from agent.ledger import append_entry

            log_decision = RebalanceDecision(
                timestamp=mapping["created_at"],
                action="wallet_created",
                pool="--",
                amount_usdc=0.0,
                percent_of_capital=0.0,
                reason=f"Circle Wallet created for {evm_address[:6]}...{evm_address[-4:]} ",
                inputs={
                    "evm_address": evm_address,
                    "circle_wallet_id": wallet_info["circle_wallet_id"],
                    "circle_address": wallet_info["circle_address"],
                    "source": wallet_info["mode"],
                },
            )
            append_entry(log_decision, status="executed")
            balance = get_circle_wallet_balance(wallet_info["circle_wallet_id"])
            result = {
                **mapping,
                "usdc_balance": balance,
                "is_new": True,
            }
            _agent.update_active_wallet(
                circle_wallet_id=result["circle_wallet_id"],
                circle_address=result["circle_address"],
                mode=result["mode"],
            )
            print(
                f"  [Wallet] NEW: {evm_address[:10]}... "
                f"-> {wallet_info['circle_wallet_id'][:8]}... "
                f"({wallet_info['mode']})"
            )
            self._json_response(result)
        except Exception as exc:
            print(f"  [Wallet] ERROR: {exc}")
            self._json_response({"error": str(exc)}, status=500)

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _file_response(self, name: str, mime: str):
        fp = DASHBOARD_DIR / name
        if not fp.exists():
            self.send_error(404, f"{name} not found in {DASHBOARD_DIR}")
            return
        body = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        pass


def main():
    global _agent
    ap = argparse.ArgumentParser(description="LiquidShift agent + dashboard")
    ap.add_argument(
        "--interval",
        type=int,
        default=LOOP_INTERVAL_S,
        help=f"Seconds between cycles (default {LOOP_INTERVAL_S})",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=DASHBOARD_PORT,
        help=f"Dashboard HTTP port (default {DASHBOARD_PORT})",
    )
    args = ap.parse_args()
    print()
    print("===================================================")
    print("  LiquidShift -- Autonomous Liquidity Agent")
    print("===================================================")
    _agent = AgentLoop(interval_s=args.interval)
    t = threading.Thread(target=_agent.run, daemon=True)
    t.start()
    srv = HTTPServer(("0.0.0.0", args.port), _Handler)
    print(f"  Dashboard : http://localhost:{args.port}")
    print("  Press Ctrl+C to stop")
    print("===================================================\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        _agent.stop()
        srv.shutdown()


if __name__ == "__main__":
    main()