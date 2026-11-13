"""MemberIdentityLink：多会员码认定为同一人的认定记录（可撤销，保留留痕）。

一个人在门店 / 私域 / 信息流可能持有不同会员码，认定后这些 member_code 归入同一
person（root 会员码），按最早消费月重新分群；撤销（status=revoked）后恢复原始分群。

幂等键 fingerprint = sha256(sorted(member_codes))：
- 同一组会员码重复认定只生效一次（active 行已存在 → IDENTITY_DUPLICATE）；
- 撤销后再次提交同一组码允许新建一条 active 行（partial unique index 只约束 active）。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.constants.enums import IdentityStatus
from src.models.base import Base, TimestampMixin, new_uuid, utcnow


def canonical_fingerprint(member_codes: list[str]) -> str:
    """同一组会员码与顺序无关的指纹：sha256('|'.join(sorted(set(codes))))。"""
    joined = "|".join(sorted(set(member_codes)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class MemberIdentityLink(Base, TimestampMixin):
    __tablename__ = "member_identity_links"
    __table_args__ = (
        # 同一组会员码在生效中只允许一条；撤销后该唯一约束不再占用（可重新认定）
        Index(
            "uq_identity_active_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index("ix_identity_status", "status"),
        {"schema": settings.db_schema},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    # 认定后该人的内部标识：取 member_codes 中字典序最小者，稳定且可复现
    person_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    member_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=IdentityStatus.ACTIVE.value, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # 认定口径的派生快照（撤销后保留，供审计与前后变化回看）
    first_order_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    first_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    code_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    revoked_by: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
