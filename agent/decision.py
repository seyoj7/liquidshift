from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from agent.data_agent import PoolSnapshot


@dataclass
class HeuristicParams:
    min_rebalance_interval_s: float = 15.0


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
        total = self.idle_usdc
        for val in self.pool_allocations.values():
            total += val
        return total

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
        decisions = []

        total_cap = state.total_capital
        if total_cap <= 0:
            return decisions

        if state.last_rebalance_time is not None:
            elapsed = (now - state.last_rebalance_time).total_seconds()
            if elapsed < p.min_rebalance_interval_s:
                for snap in snapshots:
                    decisions.append(self._hold(now, snap.pool, "Cooldown active"))
                return decisions

        best_pool = None
        max_yield = -1.0
        
        for snap in snapshots:
            y = snap.volume_1h / snap.liquidity if snap.liquidity > 0 else 0.0
            if y > max_yield:
                max_yield = y
                best_pool = snap.pool
                
        if best_pool is None or max_yield == 0.0:
            for snap in snapshots:
                decisions.append(self._hold(now, snap.pool, "Zero yield across all pools"))
            return decisions

        current_best_alloc = state.pool_allocations.get(best_pool, 0.0)
        
        if current_best_alloc >= total_cap * 0.999:
            for snap in snapshots:
                decisions.append(
                    self._hold(
                        now, snap.pool,
                        f"Already 100% in best pool ({best_pool}, yield {max_yield:.4f})"
                    )
                )
            return decisions

        total_withdrawn = 0.0
        for pool_name, allocated_amount in state.pool_allocations.items():
            if pool_name != best_pool and allocated_amount > 0:
                pct = allocated_amount / total_cap * 100
                decisions.append(
                    RebalanceDecision(
                        timestamp=now.isoformat(),
                        action="withdraw_to_idle",
                        pool=pool_name,
                        amount_usdc=allocated_amount,
                        percent_of_capital=round(pct, 2),
                        reason=f"Withdrawing ${allocated_amount:,.2f} from {pool_name} to move to {best_pool}",
                        inputs={"current_allocation": round(allocated_amount, 2)}
                    )
                )
                total_withdrawn += allocated_amount
                
        amount_to_move = round(state.idle_usdc + total_withdrawn, 2)
        if amount_to_move > 0:
            pct = amount_to_move / total_cap * 100
            decisions.append(
                RebalanceDecision(
                    timestamp=now.isoformat(),
                    action="move_to_pool",
                    pool=best_pool,
                    amount_usdc=amount_to_move,
                    percent_of_capital=round(pct, 2),
                    reason=f"Allocating all available capital (${amount_to_move:,.2f}) to best pool {best_pool} (yield {max_yield:.4f})",
                    inputs={"yield": round(max_yield, 6), "target": round(amount_to_move, 2)}
                )
            )

        return decisions


    @staticmethod
    def _hold(now: datetime, pool: str, reason: str) -> RebalanceDecision:
        return RebalanceDecision(
            timestamp=now.isoformat(), action="hold", pool=pool,
            amount_usdc=0.0, percent_of_capital=0.0, reason=reason, inputs={},
        )


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
        if d.action == "withdraw_to_idle":
            current = new_state.pool_allocations.get(d.pool, 0.0)
            actual = min(d.amount_usdc, current)
            new_state.pool_allocations[d.pool] = current - actual
            new_state.idle_usdc += actual
            any_action = True
            
    for d in decisions:
        if d.action == "move_to_pool":
            actual = min(d.amount_usdc, new_state.idle_usdc)
            new_state.idle_usdc -= actual
            prev = new_state.pool_allocations.get(d.pool, 0.0)
            new_state.pool_allocations[d.pool] = prev + actual
            any_action = True

    if any_action:
        new_state.last_rebalance_time = now
    return new_state


def main() -> None:
    from agent.data_agent import get_historical_snapshots

    engine = DecisionEngine()
    state = AllocationState(idle_usdc=10000.0)
    p = engine.params
    print()
    print("===================================================")
    print("  LiquidShift -- Decision Engine Demo")
    print("===================================================")
    print(f"  Starting capital : ${state.total_capital:,.2f} USDC (all idle)")
    print(f"  Params           : cooldown={p.min_rebalance_interval_s:.0f}s")
    print("===================================================")
    print()
    pools = ["Curve on Arc", "XyloNet", "DefiOnARC"]
    histories = {}
    for pool_name in pools:
        histories[pool_name] = get_historical_snapshots(
            hours=24, pool_name=pool_name, seed=42
        )
    for hour_idx in range(24):
        snapshots = []
        for pn in pools:
            snapshots.append(histories[pn][hour_idx])
            
        ts = snapshots[0].timestamp
        now = datetime.fromisoformat(ts)
        decisions = engine.evaluate(snapshots, state, now=now)
        for d in decisions:
            action_map = {"move_to_pool": ">>>", "withdraw_to_idle": "<<<", "hold": "   "}
            marker = "???"
            if d.action in action_map:
                marker = action_map[d.action]
            if d.action != "hold":
                print(f"  {ts[:16]}  {marker} {d.action:<20s}  "
                      f"${d.amount_usdc:>8,.2f}  {d.pool:<15s}  {d.reason}")
        state = apply_decisions(state, decisions, now=now)
    print()
    print("--- Final State ---")
    print(f"  Idle USDC      : ${state.idle_usdc:,.2f}")
    
    pool_items = list(state.pool_allocations.items())
    pool_items.sort()
    for pool, amt in pool_items:
        if amt > 0:
            print(f"  {pool:<15s}: ${amt:,.2f}")
    print(f"  Total capital  : ${state.total_capital:,.2f}")
    print()


if __name__ == "__main__":
    main()