from dataclasses import dataclass, replace
from datetime import datetime
from threading import Lock


@dataclass(slots=True)
class SchedulerStatusSnapshot:
    configured: bool = False
    enabled: bool = False
    interval_minutes: int | None = None
    match_limit: int | None = None
    send_empty_runs: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_result: str = "never"
    last_message: str = "Scheduler еще не выполнялся."
    created_signals: int = 0
    passed_filters_matches: int = 0
    existing_pending_matches: int = 0
    cooldown_blocked_matches: int = 0
    last_error: str | None = None


_scheduler_status = SchedulerStatusSnapshot()
_scheduler_lock = Lock()


def get_scheduler_status() -> SchedulerStatusSnapshot:
    with _scheduler_lock:
        return replace(_scheduler_status)


def update_scheduler_status(**changes) -> SchedulerStatusSnapshot:
    global _scheduler_status
    with _scheduler_lock:
        _scheduler_status = replace(_scheduler_status, **changes)
        return replace(_scheduler_status)
