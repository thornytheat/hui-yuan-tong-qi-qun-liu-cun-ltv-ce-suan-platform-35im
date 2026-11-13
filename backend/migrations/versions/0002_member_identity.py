"""add member_identity_links (一员多码认定)

建表口径以 SQLAlchemy 模型为唯一事实来源：新表由 MemberIdentityLink 模型
metadata.create_all 补齐，避免手写 DDL 与模型漂移；容器默认走 bootstrap_db.py，
本迁移用于正式环境 `alembic upgrade head`。

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""
from __future__ import annotations

from alembic import op

from src.config.settings import settings
from src.models import Base
from src.models.member_identity_link import MemberIdentityLink  # noqa: F401  确保表已注册

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"')
    Base.metadata.create_all(bind=bind, tables=[MemberIdentityLink.__table__])


def downgrade() -> None:
    bind = op.get_bind()
    MemberIdentityLink.__table__.drop(bind=bind, checkfirst=True)
