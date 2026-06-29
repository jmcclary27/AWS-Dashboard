from __future__ import annotations

from typing import Any
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

try:
    from sqlalchemy.orm import Mapped, mapped_column
except ImportError:
    Mapped = Any
    mapped_column = Column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    aws_account_id: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    role_arn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    team_tag_key: Mapped[str] = mapped_column(String(64), default="Team")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    role_arn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    billing_view_arn: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    billing_mode: Mapped[str] = mapped_column(String(32), default="payable_hybrid")
    billing_export_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_export_prefix: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    billing_export_region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    team_tag_key: Mapped[str] = mapped_column(String(64), default="Team")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConnectionAccount(Base):
    __tablename__ = "connection_accounts"
    __table_args__ = (UniqueConstraint("connection_id", "account_id", name="uq_connection_accounts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    membership_source: Mapped[str] = mapped_column(String(24), default="manual")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TeamAlias(Base):
    __tablename__ = "team_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("connections.id"), nullable=True, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    sync_type: Mapped[str] = mapped_column(String(32), default="demo")
    status: Mapped[str] = mapped_column(String(32), default="success")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_days: Mapped[int] = mapped_column(Integer, default=14)
    accounts_synced: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyAccountCost(Base):
    __tablename__ = "daily_account_costs"
    __table_args__ = (UniqueConstraint("connection_id", "account_id", "day", name="uq_daily_account_costs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    cost_usd: Mapped[float] = mapped_column(Float)


class DailyServiceCost(Base):
    __tablename__ = "daily_service_costs"
    __table_args__ = (UniqueConstraint("connection_id", "account_id", "day", "service_name", name="uq_daily_service_costs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    service_name: Mapped[str] = mapped_column(String(96), index=True)
    cost_usd: Mapped[float] = mapped_column(Float)


class DailyTeamCost(Base):
    __tablename__ = "daily_team_costs"
    __table_args__ = (UniqueConstraint("connection_id", "account_id", "day", "team_id", name="uq_daily_team_costs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    cost_usd: Mapped[float] = mapped_column(Float)


class DailyBillingTotal(Base):
    __tablename__ = "daily_billing_totals"
    __table_args__ = (UniqueConstraint("connection_id", "account_id", "day", name="uq_daily_billing_totals"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    gross_usage_usd: Mapped[float] = mapped_column(Float, default=0.0)
    credits_usd: Mapped[float] = mapped_column(Float, default=0.0)
    savings_discounts_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tax_usd: Mapped[float] = mapped_column(Float, default=0.0)
    support_usd: Mapped[float] = mapped_column(Float, default=0.0)
    marketplace_usd: Mapped[float] = mapped_column(Float, default=0.0)
    refunds_usd: Mapped[float] = mapped_column(Float, default=0.0)
    other_adjustments_usd: Mapped[float] = mapped_column(Float, default=0.0)
    net_due_usd: Mapped[float] = mapped_column(Float, default=0.0)
    source_kind: Mapped[str] = mapped_column(String(32), default="demo")


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    projected_cost_usd: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(32), default="demo-v1")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BillingForecast(Base):
    __tablename__ = "billing_forecasts"
    __table_args__ = (UniqueConstraint("connection_id", "account_id", "day", name="uq_billing_forecasts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    projected_net_due_usd: Mapped[float] = mapped_column(Float, default=0.0)
    projected_adjustments_usd: Mapped[float] = mapped_column(Float, default=0.0)
    model_version: Mapped[str] = mapped_column(String(32), default="demo-v1")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(24), default="medium")
    detected_on: Mapped[date] = mapped_column(Date, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    service_name: Mapped[str | None] = mapped_column(String(96), nullable=True)
    team_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)
    amount_delta_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, ForeignKey("connections.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(Text)
    impact_level: Mapped[str] = mapped_column(String(24), default="medium")
    estimated_monthly_savings_usd: Mapped[float] = mapped_column(Float, default=0.0)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    service_name: Mapped[str | None] = mapped_column(String(96), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
