"""回测进度上报（供 SSE / 前端实时展示）。"""
from __future__ import annotations

from typing import Any, Callable, Optional


class ProgressReporter:
    """将回测各阶段事件推送给回调（线程安全由调用方保证）。"""

    def __init__(self, callback: Optional[Callable[[dict[str, Any]], None]] = None):
        self.callback = callback

    def emit(self, event: dict[str, Any]) -> None:
        if not self.callback:
            return
        try:
            self.callback(event)
        except Exception:
            pass

    def stage(
        self,
        step: int,
        total: int,
        stage_id: str,
        message: str,
        percent: float | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.emit(
            {
                "type": "stage",
                "step": step,
                "total": total,
                "stage": stage_id,
                "message": message,
                "percent": percent,
                "detail": detail or {},
            }
        )

    def log(self, message: str) -> None:
        self.emit({"type": "log", "message": message})

    def shapley_subset(
        self,
        current: int,
        total: int,
        subset: list[str],
        subset_return: float,
        percent: float,
        subset_label: str = "",
        subset_full: str = "",
    ) -> None:
        self.emit(
            {
                "type": "shapley",
                "current": current,
                "total": total,
                "subset": subset,
                "subset_label": subset_label,
                "subset_full": subset_full,
                "subset_return": subset_return,
                "percent": percent,
            }
        )

    def partial_shapley(self, values: dict[str, float]) -> None:
        self.emit({"type": "partial_shapley", "values": values})

    def data_snapshot(self, stocks: int, trading_days: int) -> None:
        self.emit(
            {
                "type": "data_snapshot",
                "stocks": stocks,
                "trading_days": trading_days,
            }
        )

    def role_factor_done(
        self,
        role: str,
        months: int,
        sample_stocks: list[str],
        done: int,
        total: int,
        percent: float,
        sample_labels: list[str] | None = None,
    ) -> None:
        self.emit(
            {
                "type": "role_factor",
                "role": role,
                "months": months,
                "sample_stocks": sample_stocks,
                "sample_labels": sample_labels or sample_stocks,
                "done": done,
                "total": total,
                "percent": percent,
            }
        )

    def pipeline_result(self, total_return: float, monthly: list[dict]) -> None:
        self.emit(
            {
                "type": "pipeline",
                "total_return": total_return,
                "monthly": monthly,
            }
        )
