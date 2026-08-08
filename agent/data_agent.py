import math
import os
import random
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from agent.config import ARC_TESTNET_RPC_URL
from agent.circle_wallet import transfer_usdc
from web3 import Web3


@dataclass
class PoolSnapshot:
    timestamp: str
    pool: str
    volume_1h: float
    volume_24h_avg: float
    liquidity: float
    source: str
    volatility: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


POOLS = [
    {
        "id": "curve_on_arc",
        "name": "Curve on Arc",
        "env_key": "CURVE_POOL_ADDRESS",
    },
    {
        "id": "xylonet",
        "name": "XyloNet",
        "env_key": "XYLONET_POOL_ADDRESS",
    },
    {
        "id": "defionarc",
        "name": "DefiOnARC",
        "env_key": "DEFIONARC_POOL_ADDRESS",
    },
]
SWAP_EVENT_ABI = {
    "anonymous": False,
    "inputs": [
        {"indexed": True, "name": "sender", "type": "address"},
        {"indexed": False, "name": "amount0In", "type": "uint256"},
        {"indexed": False, "name": "amount1In", "type": "uint256"},
        {"indexed": False, "name": "amount0Out", "type": "uint256"},
        {"indexed": False, "name": "amount1Out", "type": "uint256"},
        {"indexed": True, "name": "to", "type": "address"},
    ],
    "name": "Swap",
    "type": "event",
}
_MAX_LOG_RANGE = 2000
_24H_SAMPLE_WINDOWS = 4


def _get_logs_batched(contract, from_block: int, to_block: int) -> list:
    all_events: list = []
    cursor = from_block
    while cursor <= to_block:
        batch_end = min(cursor + _MAX_LOG_RANGE - 1, to_block)
        try:
            batch = contract.events.Swap.get_logs(from_block=cursor, to_block=batch_end)
            all_events.extend(batch)
        except Exception:
            pass
        cursor = batch_end + 1
    return all_events


def _try_live_snapshot(w3: Web3, pool_cfg: dict, now: datetime) -> Optional[PoolSnapshot]:
    address = os.getenv(pool_cfg["env_key"])
    if not address:
        return None
    try:
        address = Web3.to_checksum_address(address)
        contract = w3.eth.contract(
            address=address,
            abi=[SWAP_EVENT_ABI],
        )
        current_block = w3.eth.block_number
        blocks_1h = 3600
        from_block_1h = max(0, current_block - blocks_1h)
        events_1h = _get_logs_batched(contract, from_block_1h, current_block)
        volume_1h = _sum_swap_volume(events_1h)
        sample_volume_total = 0.0
        samples_taken = 0
        for i in range(_24H_SAMPLE_WINDOWS):
            offset = int(blocks_1h * (24 / _24H_SAMPLE_WINDOWS) * i)
            sample_end = max(0, current_block - offset)
            sample_start = max(0, sample_end - blocks_1h)
            if sample_start >= sample_end:
                continue
            sample_events = _get_logs_batched(contract, sample_start, sample_end)
            sample_volume_total += _sum_swap_volume(sample_events)
            samples_taken += 1
        if samples_taken > 0:
            volume_24h_avg = sample_volume_total / samples_taken
        else:
            volume_24h_avg = 0.0
        raw_balance = w3.eth.get_balance(address)
        liquidity = float(raw_balance) / 1e18
        if volume_1h == 0 and volume_24h_avg == 0:
            return None
        volatility = min(1.0, volume_1h / max(volume_24h_avg, 1.0) - 1.0)
        volatility = max(0.0, volatility)
        return PoolSnapshot(
            timestamp=now.isoformat(),
            pool=pool_cfg["name"],
            volume_1h=round(volume_1h, 2),
            volume_24h_avg=round(volume_24h_avg, 2),
            liquidity=round(liquidity, 2),
            source="live",
            volatility=round(volatility, 4),
        )
    except Exception as exc:
        print(f"  [live] {pool_cfg['name']}: query failed ({exc})")
        return None


def _sum_swap_volume(events: list) -> float:
    total = 0
    for evt in events:
        args = evt.get("args", {})
        total += args.get("amount0In", 0) + args.get("amount0Out", 0)
    return float(total) / 1e18


_SIM_PROFILES = {
    "Curve on Arc": {
        "base_volume": 2_840_000.0,     # ~2.8M hourly like a mature stableswap
        "base_liquidity": 48_500_000.0,  # ~48.5M TVL
        "volume_noise": 0.35,
        "peak_hour_utc": 14,
        "liq_drift": 0.04,              # LP inflow/outflow amplitude
        "spike_chance": 0.08,            # 8% chance of a volume spike per snapshot
        "spike_mult_range": (2.5, 6.0),  # spike multiplier
        "weekend_dip": 0.35,             # 35% volume drop on weekends
        "fee_tier": 0.0004,              # 4 bps (Curve-style)
    },
    "XyloNet": {
        "base_volume": 920_000.0,        # ~920K hourly, mid-tier AMM
        "base_liquidity": 12_700_000.0,  # ~12.7M TVL
        "volume_noise": 0.45,
        "peak_hour_utc": 16,
        "liq_drift": 0.07,
        "spike_chance": 0.12,
        "spike_mult_range": (2.0, 8.0),
        "weekend_dip": 0.25,
        "fee_tier": 0.003,               # 30 bps
    },
    "DefiOnARC": {
        "base_volume": 410_000.0,        # ~410K hourly, newer/smaller pool
        "base_liquidity": 5_200_000.0,   # ~5.2M TVL
        "volume_noise": 0.55,
        "peak_hour_utc": 13,
        "liq_drift": 0.10,
        "spike_chance": 0.15,
        "spike_mult_range": (1.8, 10.0),
        "weekend_dip": 0.18,
        "fee_tier": 0.003,
    },
}


def _simulated_snapshot(pool_name: str, ts: datetime, rng: random.Random) -> PoolSnapshot:
    profile = _SIM_PROFILES.get(pool_name, _SIM_PROFILES["Curve on Arc"])
    hour = ts.hour + ts.minute / 60.0
    peak = profile["peak_hour_utc"]
    t_seconds = ts.timestamp()
    pool_seed = hash(pool_name) % 100_000

    # --- Time-of-day curve (double-peaked: EU + US session) ---
    phase_main = 2 * math.pi * (hour - peak) / 24.0
    phase_secondary = 2 * math.pi * (hour - (peak + 5) % 24) / 24.0
    time_mult = 1.0 + 0.45 * math.cos(phase_main) + 0.20 * math.cos(phase_secondary)

    # --- Weekend dip (Sat=5, Sun=6) ---
    weekday = ts.weekday()
    if weekday == 5:
        time_mult *= (1.0 - profile["weekend_dip"] * 0.7)
    elif weekday == 6:
        time_mult *= (1.0 - profile["weekend_dip"])

    # --- Multi-frequency noise for organic feel ---
    w1 = math.sin(t_seconds / 3600.0 + pool_seed)
    w2 = math.sin(t_seconds / 900.0 + pool_seed * 1.7) * 0.6
    w3 = math.sin(t_seconds / 180.0 + pool_seed * 3.1) * 0.3
    w4 = math.sin(t_seconds / 45.0 + pool_seed * 5.3) * 0.15
    smooth_noise = (w1 + w2 + w3 + w4) / 2.05
    noise = 1.0 + smooth_noise * profile["volume_noise"]
    noise = max(0.15, noise)

    volume_1h = profile["base_volume"] * time_mult * noise

    # --- Occasional volume spike (whale trade / liquidation cascade) ---
    spike_hash = int(t_seconds / 60) ^ pool_seed
    if (spike_hash % 1000) / 1000.0 < profile["spike_chance"]:
        lo, hi = profile["spike_mult_range"]
        spike_t = ((spike_hash % 997) / 997.0)
        spike_mult = lo + (hi - lo) * spike_t
        volume_1h *= spike_mult

    # --- 24h average: slow-moving, daily seasonal drift ---
    day_of_year = ts.timetuple().tm_yday
    daily_drift = 1.0 + 0.08 * math.sin(2 * math.pi * day_of_year / 7) \
                      + 0.04 * math.sin(2 * math.pi * day_of_year / 30)
    volume_24h_avg = profile["base_volume"] * daily_drift

    # --- Liquidity: mean-reverting with LP inflow/outflow cycles ---
    liq_slow = math.sin(t_seconds / 7200.0 + pool_seed * 0.7) * 0.6
    liq_med  = math.sin(t_seconds / 1800.0 + pool_seed * 1.3) * 0.3
    liq_fast = math.sin(t_seconds / 300.0 + pool_seed * 2.9) * 0.1
    liq_factor = 1.0 + (liq_slow + liq_med + liq_fast) * profile["liq_drift"]
    liquidity = profile["base_liquidity"] * liq_factor

    # --- Volatility: derived from volume ratio with damping ---
    vol_ratio = volume_1h / max(volume_24h_avg, 1.0)
    raw_vol = abs(vol_ratio - 1.0)
    volatility = min(1.0, max(0.0, raw_vol * 0.8 + 0.02 * abs(smooth_noise)))

    return PoolSnapshot(
        timestamp=ts.isoformat(),
        pool=pool_name,
        volume_1h=round(volume_1h, 2),
        volume_24h_avg=round(volume_24h_avg, 2),
        liquidity=round(liquidity, 2),
        source="simulated",
        volatility=round(volatility, 4),
    )


def get_current_snapshots(w3: Optional[Web3] = None) -> list[PoolSnapshot]:
    now = datetime.now(timezone.utc)
    results = []
    print(f"  [data] Querying {len(POOLS)} liquidity pools...")
    for pool_cfg in POOLS:
        snap = _try_live_snapshot(w3, pool_cfg, now)
        if not snap:
            snap = _simulated_snapshot(pool_cfg["name"], now, random.Random())
        results.append(snap)
    return results


def request_pool_data(w3: Web3, strategy_wallet_id: str, data_agent_wallet: dict) -> list[PoolSnapshot]:
    from agent.decision import RebalanceDecision
    from agent.ledger import append_entry
    from agent.config import DATA_FEE_USDC
    now = datetime.now(timezone.utc)
    data_agent_address = data_agent_wallet.get("circle_address")

    # Nanopayment fee: deliberately tiny (default 0.0001 USDC) so it sits well
    # below expected per-cycle strategy earnings, keeping the agent net profitable.
    # This models Circle's Nanopayments pattern for agent-to-agent microtransactions.
    data_fee = DATA_FEE_USDC

    try:
        print(f"  [data] Requesting pool data... Paying {data_fee} USDC to Data Agent ({data_agent_address[:6]}...)")
        transfer = transfer_usdc(strategy_wallet_id, data_agent_address, data_fee)

        log_decision = RebalanceDecision(
            timestamp=now.isoformat(),
            action="data_fee",
            pool="Data Agent",
            amount_usdc=data_fee,
            percent_of_capital=0.0,
            reason="Nanopayment for pool data snapshot",
            inputs={
                "strategy_wallet_id": strategy_wallet_id,
                "data_agent_address": data_agent_address,
            },
        )
        append_entry(log_decision, status="executed", tx_hash=transfer.get("tx_hash"))
        
        # In a real system we might block here until the transaction confirms or we get a websocket push,
        # but the transfer_usdc function currently blocks and waits for INITIATED/PENDING to pass if live.
        # We can just return the snapshots here.
        return get_current_snapshots(w3)
    except Exception as exc:
        print(f"  [!!] Failed to pay Data Agent for pool data: {exc}")
        # Return an empty list if data fee payment fails
        return []


def get_historical_snapshots(
    hours: int = 24,
    pool_name: str = "Curve on Arc",
    seed: int = 42,
) -> list[PoolSnapshot]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours - 1)
    snapshots = []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        snap = _simulated_snapshot(pool_name, ts, rng)
        snapshots.append(snap)
    return snapshots


def _print_table(snapshots: list[PoolSnapshot]) -> None:
    hdr = (
        f"{'Timestamp':>22s}  {'Pool':<15s}  {'Vol 1h':>10s}  "
        f"{'Vol 24h Avg':>11s}  {'Liquidity':>11s}  {'Vol':>6s}  {'Source':<10s}"
    )
    print(hdr)
    print("-" * len(hdr))
    for s in snapshots:
        ts_short = s.timestamp[11:19] if "T" in s.timestamp else s.timestamp[:19]
        print(
            f"{s.timestamp[:22]:>22s}  {s.pool:<15s}  "
            f"${s.volume_1h:>9,.0f}  ${s.volume_24h_avg:>10,.0f}  "
            f"${s.liquidity:>10,.0f}  {s.volatility:>5.2f}  "
            f"{s.source:<10s}"
        )


def main() -> None:
    print()
    print("===================================================")
    print("  LiquidShift -- Data Feed Test (24h History)")
    print("===================================================")
    print()
    print("[Current snapshots — all pools]")
    print()
    current = get_current_snapshots()
    _print_table(current)
    print()
    for pool_cfg in POOLS:
        name = pool_cfg["name"]
        print(f"[24h simulated history — {name}]")
        print()
        history = get_historical_snapshots(hours=24, pool_name=name)
        _print_table(history)
        print()


if __name__ == "__main__":
    main()
