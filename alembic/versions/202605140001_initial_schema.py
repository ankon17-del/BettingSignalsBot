"""initial schema

Revision ID: 202605140001
Revises:
Create Date: 2026-05-14 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "202605140001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    risk_profile = sa.Enum("conservative", "normal", "aggressive", name="riskprofile")
    signal_status = sa.Enum("pending", "won", "lost", "void", "skipped", name="signalstatus")
    reliability = sa.Enum("low", "medium", "high", name="reliability")
    impact = sa.Enum("low", "medium", "high", name="impact")
    risk_profile.create(op.get_bind(), checkfirst=True)
    signal_status.create(op.get_bind(), checkfirst=True)
    reliability.create(op.get_bind(), checkfirst=True)
    impact.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("bankroll", sa.Float(), nullable=False),
        sa.Column("initial_bankroll", sa.Float(), nullable=False),
        sa.Column("base_unit_percent", sa.Float(), nullable=False),
        sa.Column("risk_profile", risk_profile, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=False)

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sport", sa.String(length=80), nullable=False),
        sa.Column("league", sa.String(length=255), nullable=False),
        sa.Column("match_name", sa.String(length=255), nullable=False),
        sa.Column("home_team", sa.String(length=255), nullable=False),
        sa.Column("away_team", sa.String(length=255), nullable=False),
        sa.Column("market", sa.String(length=255), nullable=False),
        sa.Column("bookmaker_name", sa.String(length=255), nullable=False),
        sa.Column("odds", sa.Float(), nullable=False),
        sa.Column("bookmaker_probability", sa.Float(), nullable=False),
        sa.Column("model_probability", sa.Float(), nullable=False),
        sa.Column("value_percent", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=50), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("stake_percent", sa.Float(), nullable=False),
        sa.Column("recommended_stake", sa.Float(), nullable=False),
        sa.Column("status", signal_status, nullable=False),
        sa.Column("profit", sa.Float(), nullable=False),
        sa.Column("match_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_signals_status"), "signals", ["status"], unique=False)

    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("reliability", reliability, nullable=False),
        sa.Column("impact", impact, nullable=False),
        sa.Column("affected_team", sa.String(length=255), nullable=True),
        sa.Column("affected_player", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "signal_news_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("news_item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["news_item_id"], ["news_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "bankroll_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("bankroll_before", sa.Float(), nullable=False),
        sa.Column("bankroll_after", sa.Float(), nullable=False),
        sa.Column("change_amount", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bankroll_history_user_id"), "bankroll_history", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bankroll_history_user_id"), table_name="bankroll_history")
    op.drop_table("bankroll_history")
    op.drop_table("signal_news_links")
    op.drop_table("news_items")
    op.drop_index(op.f("ix_signals_status"), table_name="signals")
    op.drop_table("signals")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
    sa.Enum(name="impact").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="reliability").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="signalstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="riskprofile").drop(op.get_bind(), checkfirst=True)

