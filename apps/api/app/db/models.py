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
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    sync_type: Mapped[str] = mapped_column(String(32), default="demo")
    status: Mapped[str] = mapped_column(String(32), default="success")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyAccountCost(Base):
    __tablename__ = "daily_account_costs"
    __table_args__ = (UniqueConstraint("account_id", "day", name="uq_daily_account_costs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    cost_usd: Mapped[float] = mapped_column(Float)


class DailyServiceCost(Base):
    __tablename__ = "daily_service_costs"
    __table_args__ = (UniqueConstraint("account_id", "day", "service_name", name="uq_daily_service_costs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    service_name: Mapped[str] = mapped_column(String(96), index=True)
    cost_usd: Mapped[float] = mapped_column(Float)


class DailyTeamCost(Base):
    __tablename__ = "daily_team_costs"
    __table_args__ = (UniqueConstraint("account_id", "day", "team_id", name="uq_daily_team_costs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    cost_usd: Mapped[float] = mapped_column(Float)


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    projected_cost_usd: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(32), default="demo-v1")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
