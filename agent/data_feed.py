import math
import os
import random
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from agent.config import ARC_TESTNET_RPC_URL
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
        "base_volume": 5000.0,
        "base_liquidity": 120000.0,
        "volume_noise": 0.25,
        "peak_hour_utc": 14,
    },
    "XyloNet": {
        "base_volume": 3200.0,
        "base_liquidity": 80000.0,
        "volume_noise": 0.30,
        "peak_hour_utc": 15,
    },
    "DefiOnARC": {
        "base_volume": 1800.0,
        "base_liquidity": 45000.0,
        "volume_noise": 0.35,
        "peak_hour_utc": 13,
    },
}


def _simulated_snapshot(pool_name: str, ts: datetime, rng: random.Random) -> PoolSnapshot:
    profile = _SIM_PROFILES.get(pool_name, _SIM_PROFILES["Curve on Arc"])
    hour = ts.hour + ts.minute / 60.0
    peak = profile["peak_hour_utc"]
    phase = 2 * math.pi * (hour - peak) / 24.0
    time_mult = 1.0 + 0.6 * math.cos(phase)
    noise = 1.0 + rng.gauss(0, profile["volume_noise"])
    noise = max(0.1, noise)
    volume_1h = profile["base_volume"] * time_mult * noise
    day_of_year = ts.timetuple().tm_yday
    daily_drift = 1.0 + 0.05 * math.sin(2 * math.pi * day_of_year / 30)
    volume_24h_avg = profile["base_volume"] * daily_drift
    liq_noise = 1.0 + rng.gauss(0, 0.02)
    liquidity = profile["base_liquidity"] * liq_noise
    vol_ratio = volume_1h / max(volume_24h_avg, 1.0)
    volatility = min(1.0, max(0.0, abs(vol_ratio - 1.0)))
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
    rng = random.Random()
    if w3 is None:
        rpc_url = ARC_TESTNET_RPC_URL
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            if not w3.is_connected():
                w3 = None
        except Exception:
            w3 = None
    snapshots: list[PoolSnapshot] = []
    for pool_cfg in POOLS:
        snap = None
        if w3 is not None:
            snap = _try_live_snapshot(w3, pool_cfg, now)
        if snap is None:
            snap = _simulated_snapshot(pool_cfg["name"], now, rng)
        snapshots.append(snap)
    return snapshots


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
