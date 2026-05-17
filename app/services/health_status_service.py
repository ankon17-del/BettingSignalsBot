from app.db.health_repository import HealthStatusRepository
from app.db.session import session_context
from app.services.provider_state import ProviderStatusSnapshot, set_provider_status
from app.services.runtime_state import SchedulerStatusSnapshot, set_scheduler_status


class HealthStatusService:
    async def persist_provider_status(self, snapshot: ProviderStatusSnapshot) -> None:
        async with session_context() as session:
            repo = HealthStatusRepository(session)
            await repo.upsert(
                "provider",
                snapshot.name,
                {
                    "enabled": snapshot.enabled,
                    "configured": snapshot.configured,
                    "last_attempt_at": snapshot.last_attempt_at,
                    "last_success_at": snapshot.last_success_at,
                    "last_status": snapshot.last_status,
                    "last_message": snapshot.last_message,
                    "last_error": snapshot.last_error,
                    "items_count": snapshot.items_count,
                    "cache_hit": snapshot.cache_hit,
                    "cooldown_until": snapshot.cooldown_until,
                },
            )

    async def persist_scheduler_status(self, snapshot: SchedulerStatusSnapshot) -> None:
        async with session_context() as session:
            repo = HealthStatusRepository(session)
            await repo.upsert(
                "scheduler",
                "olimp_auto_scan",
                {
                    "enabled": snapshot.enabled,
                    "configured": snapshot.configured,
                    "interval_minutes": snapshot.interval_minutes,
                    "match_limit": snapshot.match_limit,
                    "send_empty_runs": snapshot.send_empty_runs,
                    "last_started_at": snapshot.last_started_at,
                    "last_finished_at": snapshot.last_finished_at,
                    "last_result": snapshot.last_result,
                    "last_message": snapshot.last_message,
                    "created_signals": snapshot.created_signals,
                    "passed_filters_matches": snapshot.passed_filters_matches,
                    "existing_pending_matches": snapshot.existing_pending_matches,
                    "cooldown_blocked_matches": snapshot.cooldown_blocked_matches,
                    "last_error": snapshot.last_error,
                },
            )

    async def load_persisted_state(self) -> None:
        async with session_context() as session:
            repo = HealthStatusRepository(session)
            rows = await repo.list_all()

        for row in rows:
            if row.component_type == "provider":
                set_provider_status(
                    ProviderStatusSnapshot(
                        name=row.component_name,
                        enabled=row.enabled,
                        configured=row.configured,
                        last_attempt_at=row.last_attempt_at,
                        last_success_at=row.last_success_at,
                        last_status=row.last_status,
                        last_message=row.last_message,
                        last_error=row.last_error,
                        items_count=row.items_count,
                        cache_hit=row.cache_hit,
                        cooldown_until=row.cooldown_until,
                    )
                )
            elif row.component_type == "scheduler":
                set_scheduler_status(
                    SchedulerStatusSnapshot(
                        configured=row.configured,
                        enabled=row.enabled,
                        interval_minutes=row.interval_minutes,
                        match_limit=row.match_limit,
                        send_empty_runs=row.send_empty_runs,
                        last_started_at=row.last_started_at,
                        last_finished_at=row.last_finished_at,
                        last_result=row.last_result or "never",
                        last_message=row.last_message,
                        created_signals=row.created_signals,
                        passed_filters_matches=row.passed_filters_matches,
                        existing_pending_matches=row.existing_pending_matches,
                        cooldown_blocked_matches=row.cooldown_blocked_matches,
                        last_error=row.last_error,
                    )
                )
