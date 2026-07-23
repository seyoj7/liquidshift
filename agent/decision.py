from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from agent.data_feed import PoolSnapshot


@dataclass
class HeuristicParams:
    min_rebalance_interval_s: float = 60.0
    min_allocation_shift_pct: float = 5.0


@dataclass
class RebalanceDecision:
    timestamp: str
    action: str
    pool: str
    amount_usdc: float
    percent_of_capital: float
    reason: str
    inputs: dict

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class AllocationState:
    idle_usdc: float = 0.0
    pool_allocations: dict = field(default_factory=dict)
    last_rebalance_time: Optional[datetime] = None

    @property
    def total_capital(self) -> float:
        return self.idle_usdc + sum(self.pool_allocations.values())

    def copy(self) -> "AllocationState":
        return AllocationState(
            idle_usdc=self.idle_usdc,
            pool_allocations=dict(self.pool_allocations),
            last_rebalance_time=self.last_rebalance_time,
        )


class DecisionEngine:
    def __init__(self, params: Optional[HeuristicParams] = None) -> None:
        self.params = params or HeuristicParams()

    def evaluate(
        self,
        snapshots: list[PoolSnapshot],
        state: AllocationState,
        now: Optional[datetime] = None,
    ) -> list[RebalanceDecision]:
        if now is None:
            now = datetime.now(timezone.utc)
        p = self.params
        decisions: list[RebalanceDecision] = []

        total_cap = state.total_capital
        if total_cap <= 0:
            return decisions

        cooldown_active = False
        if state.last_rebalance_time is not None:
            elapsed = (now - state.last_rebalance_time).total_seconds()
            cooldown_active = elapsed < p.min_rebalance_interval_s

        if cooldown_active:

            for snap in snapshots:
                decisions.append(
                    RebalanceDecision(
                        timestamp=now.isoformat(),
                        action="hold",
                        pool=snap.pool,
                        amount_usdc=0.0,
                        percent_of_capital=0.0,
                        reason="Cooldown active - skipping rebalance",
                        inputs={"cooldown_active": True},
                    )
                )
            return decisions

        pool_yields = {}
        total_yield = 0.0
        for snap in snapshots:
            if snap.liquidity > 0:
                y = snap.volume_1h / snap.liquidity
                pool_yields[snap.pool] = y
                total_yield += y

        if total_yield == 0.0:

            target_allocs = {s.pool: total_cap / len(snapshots) for s in snapshots}
        else:

            target_allocs = {pool: (y / total_yield) * total_cap for pool, y in pool_yields.items()}

        needs_rebalance = False
        for snap in snapshots:
            current = state.pool_allocations.get(snap.pool, 0.0)
            target = target_allocs.get(snap.pool, 0.0)
            shift_pct = abs(target - current) / total_cap * 100
            if shift_pct >= p.min_allocation_shift_pct:
                needs_rebalance = True
                break

        if not needs_rebalance:
            for snap in snapshots:
                decisions.append(
                    RebalanceDecision(
                        timestamp=now.isoformat(),
                        action="hold",
                        pool=snap.pool,
                        amount_usdc=0.0,
                        percent_of_capital=0.0,
                        reason="Target allocation close to current (below shift threshold)",
                        inputs={"target": round(target_allocs.get(snap.pool, 0.0), 2)},
                    )
                )
            return decisions

        for snap in snapshots:
            current = state.pool_allocations.get(snap.pool, 0.0)
            target = target_allocs.get(snap.pool, 0.0)
            if current > target:
                withdraw_amount = round(current - target, 2)
                if withdraw_amount > 0:
                    pct = (withdraw_amount / total_cap) * 100
                    decisions.append(
                        RebalanceDecision(
                            timestamp=now.isoformat(),
                            action="withdraw_to_idle",
                            pool=snap.pool,
                            amount_usdc=withdraw_amount,
                            percent_of_capital=round(pct, 2),
                            reason=f"Yield realignment: Withdrawing ${withdraw_amount:,.2f} from {snap.pool}",
                            inputs={
                                "yield": round(pool_yields.get(snap.pool, 0.0), 6),
                                "current": current,
                                "target": round(target, 2),
                            },
                        )
                    )

        for snap in snapshots:
            current = state.pool_allocations.get(snap.pool, 0.0)
            target = target_allocs.get(snap.pool, 0.0)
            if current < target:
                move_amount = round(target - current, 2)
                if move_amount > 0:
                    pct = (move_amount / total_cap) * 100
                    decisions.append(
                        RebalanceDecision(
                            timestamp=now.isoformat(),
                            action="move_to_pool",
                            pool=snap.pool,
                            amount_usdc=move_amount,
                            percent_of_capital=round(pct, 2),
                            reason=f"Yield realignment: Allocating ${move_amount:,.2f} to {snap.pool}",
                            inputs={
                                "yield": round(pool_yields.get(snap.pool, 0.0), 6),
                                "current": current,
                                "target": round(target, 2),
                            },
                        )
                    )

        return decisions


def apply_decisions(
    state: AllocationState,
    decisions: list[RebalanceDecision],
    now: Optional[datetime] = None,
) -> AllocationState:
    if now is None:
        now = datetime.now(timezone.utc)
    new_state = state.copy()
    any_action = False
    for d in decisions:
        if d.action == "move_to_pool":
            actual = min(d.amount_usdc, new_state.idle_usdc)
            new_state.idle_usdc -= actual
            prev = new_state.pool_allocations.get(d.pool, 0.0)
            new_state.pool_allocations[d.pool] = prev + actual
            any_action = True
        elif d.action == "withdraw_to_idle":
            current = new_state.pool_allocations.get(d.pool, 0.0)
            actual = min(d.amount_usdc, current)
            new_state.pool_allocations[d.pool] = current - actual
            new_state.idle_usdc += actual
            any_action = True
    if any_action:
        new_state.last_rebalance_time = now
    return new_state


def main() -> None:
    from agent.data_feed import get_historical_snapshots

    engine = DecisionEngine()
    state = AllocationState(idle_usdc=10000.0)
    print()
    print("===================================================")
    print("  LiquidShift -- Decision Engine Demo")
    print("===================================================")
    print(f"  Starting capital : ${state.total_capital:,.2f} USDC (all idle)")
    print(f"  Params           : threshold={engine.params.volume_threshold_mult}x, " f"max_move=${engine.params.max_single_move_usdc:,.0f}, " f"cooldown={engine.params.min_rebalance_interval_s/60:.0f}min")
    print("===================================================")
    print()
    pools = ["Curve on Arc", "XyloNet", "DefiOnARC"]
    histories = {}
    for pool_name in pools:
        histories[pool_name] = get_historical_snapshots(hours=24, pool_name=pool_name, seed=42)
    for hour_idx in range(24):
        snapshots = [histories[p][hour_idx] for p in pools]
        ts = snapshots[0].timestamp
        now = datetime.fromisoformat(ts)
        decisions = engine.evaluate(snapshots, state, now=now)
        for d in decisions:
            marker = {
                "move_to_pool": ">>>",
                "withdraw_to_idle": "<<<",
                "hold": "   ",
            }.get(d.action, "???")
            if d.action != "hold":
                print(f"  {ts[:16]}  {marker} {d.action:<20s}  " f"${d.amount_usdc:>8,.2f}  {d.pool:<15s}  {d.reason}")
        state = apply_decisions(state, decisions, now=now)
    print()
    print("--- Final State ---")
    print(f"  Idle USDC      : ${state.idle_usdc:,.2f}")
    for pool, amt in sorted(state.pool_allocations.items()):
        if amt > 0:
            print(f"  {pool:<15s}: ${amt:,.2f}")
    print(f"  Total capital  : ${state.total_capital:,.2f}")
    print()


if __name__ == "__main__":
    main()