"""一员多码认定服务：认定 / 撤销 / 查询，认定后重建矩阵并回传前后变化。

业务规则（与 identity_core 同源）：
- 多个会员码可认定为一人，也可撤销误认；
- 认定后按最早消费月重新分群，历史订单只在首次获客渠道计一次；
- 撤销后恢复原来的分群与渠道归属（矩阵回到原始路径重建）；
- 同一认定（同组会员码，与顺序无关）重复执行只生效一次；
- 认定前后会员数、首单月与渠道归属变化随响应返回，留存矩阵 / LTV / 导出共用同一结果。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.constants import error_codes as err_codes
from src.constants.enums import IdentityStatus
from src.models.cohort import Cohort
from src.models.member_identity_link import MemberIdentityLink, canonical_fingerprint
from src.models.member_order import MemberOrder
from src.services import identity_core
from src.utils.errors import AppError
from src.utils.logger import get_logger

logger = get_logger("cohortltv.identity")

MAX_CODES_PER_LINK = 50


# ---------------------------------------------------------------- 内部工具


def _raw_orders(db: Session) -> list[dict]:
    orders = db.execute(select(MemberOrder)).scalars().all()
    return [
        {
            "member_code": o.member_code,
            "cohort_month": o.cohort_month,
            "channel": o.channel,
            "order_month": o.order_month,
            "month_index": o.month_index,
            "amount": float(o.amount),
            "is_first_order": bool(o.is_first_order),
            "ordered_at": o.ordered_at.isoformat() if o.ordered_at else "",
        }
        for o in orders
    ]


def _active_links(db: Session) -> list[MemberIdentityLink]:
    return list(
        db.execute(
            select(MemberIdentityLink)
            .where(MemberIdentityLink.status == IdentityStatus.ACTIVE.value)
            .order_by(MemberIdentityLink.created_at.desc())
        ).scalars().all()
    )


def _rebuild(db: Session) -> dict:
    # 延迟导入避免与 retention_service 的模型层导入形成环
    from src.services import retention_service

    return retention_service.rebuild_matrix(db)


def _validate_codes(db: Session, codes: list[str]) -> list[str]:
    normalized = identity_core.normalize_codes(codes)
    if len(normalized) < 2:
        raise AppError(
            err_codes.IDENTITY_CODES_INVALID,
            detail=f"distinct_codes={len(normalized)} expected>=2",
        )
    if len(normalized) > MAX_CODES_PER_LINK:
        raise AppError(
            err_codes.IDENTITY_CODES_INVALID,
            f"一次认定最多 {MAX_CODES_PER_LINK} 个会员码",
            detail=f"distinct_codes={len(normalized)} expected<={MAX_CODES_PER_LINK}",
        )
    known = set(
        db.execute(
            select(MemberOrder.member_code)
            .where(MemberOrder.member_code.in_(normalized))
            .distinct()
        ).scalars().all()
    )
    unknown = [code for code in normalized if code not in known]
    if unknown:
        raise AppError(
            err_codes.IDENTITY_CODE_UNKNOWN,
            detail=f"unknown_codes={unknown[:10]}",
            extra={"unknown_codes": unknown},
        )
    return normalized


def _change_snapshot(
    db: Session,
    active_links: list[MemberIdentityLink],
    raw_orders: list[dict],
) -> dict:
    """认定前后：总会员数、各群规模，以及每个被认定人的首单月 / 渠道变化。"""
    before_sizes = identity_core.raw_cohort_sizes(raw_orders)
    person_map = identity_core.build_person_map([link.member_codes for link in active_links])
    resolved = identity_core.resolve_orders(raw_orders, person_map)
    after_sizes = identity_core.effective_cohort_sizes(resolved)

    affected_persons = []
    for link in active_links:
        affected_persons.append(
            identity_core.person_change_view(link.member_codes, raw_orders, resolved)
        )

    cohort_month_rows = db.execute(select(Cohort.month)).scalars().all()
    size_changes = []
    for month in sorted(set(cohort_month_rows) | set(before_sizes) | set(after_sizes)):
        before = int(before_sizes.get(month, 0))
        after = int(after_sizes.get(month, 0))
        size_changes.append(
            {"cohort_month": month, "before": before, "after": after, "delta": after - before}
        )

    return {
        "members_before": sum(before_sizes.values()),
        "members_after": sum(after_sizes.values()),
        "cohort_size_changes": size_changes,
        "persons": affected_persons,
    }


def _serialize_link(link: MemberIdentityLink) -> dict:
    return {
        "id": str(link.id),
        "person_code": link.person_code,
        "member_codes": list(link.member_codes or []),
        "code_count": int(link.code_count),
        "status": link.status,
        "fingerprint": link.fingerprint,
        "first_order_month": link.first_order_month,
        "first_channel": link.first_channel,
        "note": link.note,
        "created_by": link.created_by,
        "revoked_by": link.revoked_by,
        "created_at": link.created_at.isoformat() if link.created_at else "",
        "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
    }


# ---------------------------------------------------------------- 对外操作


def apply_link(db: Session, codes: list[str], note: str, user) -> dict:
    normalized = _validate_codes(db, codes)
    fp = canonical_fingerprint(normalized)

    existing = db.execute(
        select(MemberIdentityLink).where(MemberIdentityLink.fingerprint == fp)
    ).scalars().all()
    active_existing = [link for link in existing if link.status == IdentityStatus.ACTIVE.value]
    if active_existing:
        # 同一认定重复执行只生效一次：回显既有记录，不重建、不重复写审计
        logger.info("identity merge idempotent hit fingerprint=%s", fp[:12])
        return {
            "idempotent": True,
            "applied": False,
            "link": _serialize_link(active_existing[0]),
            "rebuild": None,
            "change": None,
        }

    conflicting = [
        link
        for link in _active_links(db)
        if set(link.member_codes or []) & set(normalized)
    ]
    if conflicting:
        raise AppError(
            err_codes.IDENTITY_CONFLICT,
            "会员码已存在生效中的认定，请先撤销原认定再重新认定",
            detail="conflicting_link_ids=" + ",".join(str(link.id) for link in conflicting),
            extra={"conflicting_link_ids": [str(link.id) for link in conflicting]},
        )

    person_code = min(normalized)
    link = MemberIdentityLink(
        person_code=person_code,
        member_codes=normalized,
        status=IdentityStatus.ACTIVE.value,
        fingerprint=fp,
        code_count=len(normalized),
        note=(note or "")[:2000],
        created_by=user.email if user else "",
    )
    try:
        # savepoint：并发下若同组认定已被另一请求写入，回滚到这里仍可继续查询并按幂等返回
        with db.begin_nested():
            db.add(link)
            db.flush()
    except IntegrityError:
        db.rollback()
        winner = db.execute(
            select(MemberIdentityLink).where(
                MemberIdentityLink.fingerprint == fp,
                MemberIdentityLink.status == IdentityStatus.ACTIVE.value,
            )
        ).scalar_one_or_none()
        if winner is not None:
            logger.info("identity merge concurrent idempotent fingerprint=%s", fp[:12])
            return {
                "idempotent": True,
                "applied": False,
                "link": _serialize_link(winner),
                "rebuild": None,
                "change": None,
            }
        raise

    # 单人首单月 / 首次获客渠道（仅本组码口径，落库用于列表与审计）
    raw_orders = _raw_orders(db)
    solo_map = identity_core.build_person_map([normalized])
    attrs = identity_core.person_first_attributes(raw_orders, solo_map)
    first_month, first_channel = attrs.get(person_code, (None, None))
    link.first_order_month = first_month
    link.first_channel = first_channel

    rebuild_summary = _rebuild(db)

    active = _active_links(db)
    change = _change_snapshot(db, active, raw_orders)
    return {
        "idempotent": False,
        "applied": True,
        "link": _serialize_link(link),
        "rebuild": rebuild_summary,
        "change": change,
    }


def revoke_link(db: Session, link_id, user) -> dict:
    link = db.get(MemberIdentityLink, link_id)
    if link is None:
        raise AppError(err_codes.IDENTITY_LINK_NOT_FOUND)
    if link.status != IdentityStatus.ACTIVE.value:
        raise AppError(
            err_codes.IDENTITY_NOT_ACTIVE,
            detail=f"link_id={link_id} status={link.status}",
        )

    raw_orders = _raw_orders(db)
    # 撤销前的变化快照（含本认定），便于页面回看「撤销恢复了什么」
    before_active = _active_links(db)
    before_change = _change_snapshot(db, before_active, raw_orders)

    link.status = IdentityStatus.REVOKED.value
    link.revoked_by = user.email if user else ""
    link.revoked_at = datetime.now(timezone.utc)
    db.flush()

    rebuild_summary = _rebuild(db)

    remaining = _active_links(db)
    after_change = _change_snapshot(db, remaining, raw_orders)
    return {
        "idempotent": False,
        "revoked": True,
        "link": _serialize_link(link),
        "rebuild": rebuild_summary,
        "change_before": before_change,
        "change": after_change,
    }


def list_links(db: Session, status: str | None = None) -> dict:
    stmt = select(MemberIdentityLink).order_by(MemberIdentityLink.created_at.desc())
    if status:
        stmt = stmt.where(MemberIdentityLink.status == status)
    links = db.execute(stmt).scalars().all()
    return {"total": len(links), "items": [_serialize_link(link) for link in links]}


def overview(db: Session) -> dict:
    """认定总览：生效 / 撤销数、认定前后会员数（原始会员码 vs 去重人数）。"""
    raw_orders = _raw_orders(db)
    active = _active_links(db)
    raw_sizes = identity_core.raw_cohort_sizes(raw_orders)
    person_map = identity_core.build_person_map([link.member_codes for link in active])
    resolved = identity_core.resolve_orders(raw_orders, person_map)
    effective_sizes = identity_core.effective_cohort_sizes(resolved)

    raw_members = db.execute(
        select(func.count(func.distinct(MemberOrder.member_code)))
    ).scalar_one()
    revoked_count = db.execute(
        select(func.count())
        .select_from(MemberIdentityLink)
        .where(MemberIdentityLink.status == IdentityStatus.REVOKED.value)
    ).scalar_one()

    return {
        "active_links": len(active),
        "revoked_links": int(revoked_count or 0),
        "members_raw": int(raw_members or 0),
        "members_effective": int(sum(effective_sizes.values())),
        "members_before": int(sum(raw_sizes.values())),
        "members_after": int(sum(effective_sizes.values())),
        "identity_mode": "merged" if active else "raw",
        "cohort_sizes": [
            {
                "cohort_month": month,
                "before": int(raw_sizes.get(month, 0)),
                "after": int(effective_sizes.get(month, 0)),
            }
            for month in sorted(set(raw_sizes) | set(effective_sizes))
        ],
    }


__all__ = ["apply_link", "list_links", "overview", "revoke_link"]
