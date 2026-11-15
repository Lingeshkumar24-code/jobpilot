import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, MetaData, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on PostgreSQL, plain JSON on SQLite (used by the fast test suite).
# Production always runs PostgreSQL; the fallback keeps unit tests honest
# without pretending a PostgreSQL-only feature exists locally.
JSONDoc = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")

# Deterministic constraint names. Without this, Alembic emits anonymous
# foreign keys that PostgreSQL names, and downgrades cannot drop them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def uuid_pk():
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def uuid_fk(target: str, **kwargs):
    return mapped_column(Uuid(as_uuid=True), **kwargs)
