import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RiskProfile(str, enum.Enum):
    conservative = "conservative"
    normal = "normal"
    aggressive = "aggressive"


class SignalStatus(str, enum.Enum):
    pending = "pending"
    won = "won"
    lost = "lost"
    void = "void"
    skipped = "skipped"


class Reliability(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Impact(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    bankroll: Mapped[float] = mapped_column(Float, nullable=False)
    initial_bankroll: Mapped[float] = mapped_column(Float, nullable=False)
    base_unit_percent: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    risk_profile: Mapped[RiskProfile] = mapped_column(Enum(RiskProfile), nullable=False, default=RiskProfile.normal)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    bankroll_history: Mapped[list["BankrollHistory"]] = relationship(back_populates="user")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport: Mapped[str] = mapped_column(String(80), nullable=False)
    league: Mapped[str] = mapped_column(String(255), nullable=False)
    match_name: Mapped[str] = mapped_column(String(255), nullable=False)
    home_team: Mapped[str] = mapped_column(String(255), nullable=False)
    away_team: Mapped[str] = mapped_column(String(255), nullable=False)
    market: Mapped[str] = mapped_column(String(255), nullable=False)
    bookmaker_name: Mapped[str] = mapped_column(String(255), nullable=False)
    odds: Mapped[float] = mapped_column(Float, nullable=False)
    bookmaker_probability: Mapped[float] = mapped_column(Float, nullable=False)
    model_probability: Mapped[float] = mapped_column(Float, nullable=False)
    value_percent: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    stake_percent: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_stake: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[SignalStatus] = mapped_column(Enum(SignalStatus), nullable=False, default=SignalStatus.pending, index=True)
    profit: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    match_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    news_links: Mapped[list["SignalNewsLink"]] = relationship(back_populates="signal", cascade="all, delete-orphan")


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    reliability: Mapped[Reliability] = mapped_column(Enum(Reliability), nullable=False, default=Reliability.medium)
    impact: Mapped[Impact] = mapped_column(Enum(Impact), nullable=False, default=Impact.medium)
    affected_team: Mapped[str | None] = mapped_column(String(255))
    affected_player: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    signal_links: Mapped[list["SignalNewsLink"]] = relationship(back_populates="news_item", cascade="all, delete-orphan")


class SignalNewsLink(Base):
    __tablename__ = "signal_news_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), nullable=False)
    news_item_id: Mapped[int] = mapped_column(ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False)

    signal: Mapped[Signal] = relationship(back_populates="news_links")
    news_item: Mapped[NewsItem] = relationship(back_populates="signal_links")


class BankrollHistory(Base):
    __tablename__ = "bankroll_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))
    bankroll_before: Mapped[float] = mapped_column(Float, nullable=False)
    bankroll_after: Mapped[float] = mapped_column(Float, nullable=False)
    change_amount: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="bankroll_history")

