"""BatchCoordinator: owns Scheduler, fans out, drains, reviews."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import bind  # noqa: E402

_emit = bind("mentat-orchestrate")


@dataclass(frozen=True)
class BatchResult:
    session_id: str
    landed: tuple[str, ...]
    ejected: tuple[str, ...]


class BatchCoordinator:
    def __init__(self, scheduler: Any, fan_out: Any, land_queue: Any, batch_review: Any) -> None:
        self._scheduler = scheduler
        self._fan_out = fan_out
        self._land_queue = land_queue
        self._batch_review = batch_review

    def run(self, plans: list[Any], session_id: str, *, holding: str = "holding") -> BatchResult:
        chunks = self._fan_out.run(plans)
        self._land_queue.drain(
            chunks,
            holding=holding,
            on_landed=self._scheduler.mark_landed,
            on_ejected=self._scheduler.mark_ejected,
            next_ready=self._scheduler.next_ready,
        )
        self._batch_review.review(session_id)
        return BatchResult(
            session_id=session_id,
            landed=tuple(self._scheduler._landed),
            ejected=tuple(self._scheduler._ejected),
        )
