from dataclasses import dataclass, replace
from datetime import datetime
from threading import Lock


@dataclass(slots=True)
class ProviderStatusSnapshot:
    name: str
    enabled: bool = False
    configured: bool = False
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_status: str = "never"
    last_message: str = "Нет данных."
    last_error: str | None = None
    items_count: int = 0
    cache_hit: bool = False
    cooldown_until: datetime | None = None


_provider_state: dict[str, ProviderStatusSnapshot] = {}
_provider_lock = Lock()


def get_provider_status(name: str) -> ProviderStatusSnapshot:
    with _provider_lock:
        snapshot = _provider_state.get(name)
        if snapshot is None:
            return ProviderStatusSnapshot(name=name)
        return replace(snapshot)


def list_provider_statuses() -> dict[str, ProviderStatusSnapshot]:
    with _provider_lock:
        return {name: replace(snapshot) for name, snapshot in _provider_state.items()}


def set_provider_status(snapshot: ProviderStatusSnapshot) -> ProviderStatusSnapshot:
    with _provider_lock:
        _provider_state[snapshot.name] = replace(snapshot)
        return replace(snapshot)


def update_provider_status(name: str, **changes) -> ProviderStatusSnapshot:
    with _provider_lock:
        current = _provider_state.get(name, ProviderStatusSnapshot(name=name))
        updated = replace(current, **changes)
        _provider_state[name] = updated
        return replace(updated)
