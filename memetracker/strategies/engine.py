from __future__ import annotations

from datetime import timedelta

from memetracker.database import Database, dt_from_str
from memetracker.models import Call, PriceSnapshot, StrategyResult
from memetracker.strategies.base import BaseStrategy
from memetracker.strategies.hold import Hold5m, Hold15m, Hold30m


STRATEGY_CLASSES: tuple[type[BaseStrategy], ...] = (
    Hold5m,
    Hold15m,
    Hold30m,
)


def strategy_names() -> list[str]:
    return [cls.name for cls in STRATEGY_CLASSES]


def strategy_sort_key(name: str) -> tuple[int, str]:
    order = {strategy_name: index for index, strategy_name in enumerate(strategy_names())}
    return (order.get(name, 999), name)


class StrategyEngine:
    def __init__(self, db: Database, track_max_hours: int = 24) -> None:
        self.db = db
        self.track_max_hours = track_max_hours
        self.active: dict[int, list[BaseStrategy]] = {}
        self.calls_by_contract: dict[str, set[int]] = {}
        self.calls: dict[int, Call] = {}

    async def register_call(self, call: Call) -> None:
        self.calls[call.id] = call
        strategies = [cls(call) for cls in STRATEGY_CLASSES]
        self.active[call.id] = strategies
        self.calls_by_contract.setdefault(call.contract_address, set()).add(call.id)
        for strategy in strategies:
            await self.db.create_strategy_result(strategy.on_call())

    async def restore(self) -> None:
        rows = await self.db.get_open_strategy_rows()
        grouped: dict[int, list[StrategyResult]] = {}
        for row in rows:
            call_id = int(row["call_id"])
            grouped.setdefault(call_id, []).append(row_to_strategy_result(row))
        for call_id, results in grouped.items():
            call = await self.db.get_call(call_id)
            if not call:
                continue
            self.calls[call_id] = call
            restored = []
            for result in results:
                cls = next((candidate for candidate in STRATEGY_CLASSES if candidate.name == result.strategy_name), None)
                if cls:
                    restored.append(cls(call, result))
            if restored:
                self.active[call_id] = restored
                self.calls_by_contract.setdefault(call.contract_address, set()).add(call_id)

    async def on_snapshot(self, snapshot: PriceSnapshot) -> None:
        call_ids = list(self.calls_by_contract.get(snapshot.contract_address, set()))
        for call_id in call_ids:
            call = self.calls.get(call_id)
            strategies = self.active.get(call_id, [])
            if not call or not strategies:
                continue
            if snapshot.timestamp - call.call_timestamp > timedelta(hours=self.track_max_hours):
                for strategy in strategies:
                    if not strategy.is_finished():
                        await self.db.update_strategy_result(strategy.expire(snapshot.timestamp))
            else:
                for strategy in strategies:
                    before = strategy.result.status
                    result = strategy.on_price_update(snapshot)
                    if result.status != before or not strategy.is_finished():
                        await self.db.update_strategy_result(result)
            self._prune_call(call_id)

    def active_contracts(self) -> set[str]:
        return {contract for contract, ids in self.calls_by_contract.items() if ids}

    def _prune_call(self, call_id: int) -> None:
        strategies = self.active.get(call_id, [])
        if strategies and all(strategy.is_finished() for strategy in strategies):
            call = self.calls.get(call_id)
            self.active.pop(call_id, None)
            if call:
                ids = self.calls_by_contract.get(call.contract_address)
                if ids:
                    ids.discard(call_id)


def row_to_strategy_result(row: object) -> StrategyResult:
    return StrategyResult(
        call_id=int(row["call_id"]),
        strategy_name=str(row["strategy_name"]),
        status=str(row["status"]),
        entry_price=float(row["entry_price"]),
        exit_price=row["exit_price"],
        exit_timestamp=dt_from_str(row["exit_timestamp"]) if row["exit_timestamp"] else None,
        roi_percent=row["roi_percent"],
        max_roi_percent=float(row["max_roi_percent"] or 0),
        max_drawdown_percent=float(row["max_drawdown_percent"] or 0),
        duration_seconds=row["duration_seconds"],
        metadata_json=str(row["metadata_json"] or "{}"),
    )
