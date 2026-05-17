from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BankrollHistory, Signal


@dataclass(slots=True)
class SignalHistoryEntry:
    signal: Signal
    resolved_by: str
    status_label: str
    scoreline: str | None
    provider_status: str | None
    closed_reason: str
    bankroll_at_close: float
    closed_at: object | None


class SignalHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_recent_settled_signals(self, user_id: int, limit: int = 10) -> list[SignalHistoryEntry]:
        result = await self.session.execute(
            select(BankrollHistory, Signal)
            .join(Signal, Signal.id == BankrollHistory.signal_id)
            .where(
                BankrollHistory.user_id == user_id,
                BankrollHistory.signal_id.is_not(None),
            )
            .order_by(BankrollHistory.created_at.desc(), BankrollHistory.id.desc())
            .limit(limit)
        )

        entries: list[SignalHistoryEntry] = []
        for history_row, signal in result.all():
            parsed = self._parse_reason(history_row.reason)
            if parsed is None:
                continue
            resolved_by, status_label, scoreline, provider_status = parsed
            entries.append(
                SignalHistoryEntry(
                    signal=signal,
                    resolved_by=resolved_by,
                    status_label=status_label,
                    scoreline=scoreline,
                    provider_status=provider_status,
                    closed_reason=history_row.reason,
                    bankroll_at_close=history_row.bankroll_after,
                    closed_at=signal.closed_at or history_row.created_at,
                )
            )
        return entries

    @staticmethod
    def _parse_reason(reason: str) -> tuple[str, str, str | None, str | None] | None:
        if reason.startswith("auto_signal_"):
            parts = reason.split("|")
            status_label = parts[0].removeprefix("auto_signal_")
            scoreline = parts[1] if len(parts) > 1 else None
            provider_status = parts[2] if len(parts) > 2 else None
            return "AUTO", status_label.upper(), scoreline, provider_status
        if reason.startswith("signal_"):
            status_label = reason.removeprefix("signal_")
            return "MANUAL", status_label.upper(), None, None
        return None
