"""算法 1：同期群留存矩阵重建（订单事实 → 留存格）。

口径见 `retention_core`（纯函数）；本模块只负责读订单聚合、整表重建与落库。

两条数据路径，共用同一份 retention_core / ltv 口径：
- 原始路径（无生效认定）：直接 SQL 聚合 member_orders 的原始分群与渠道；
- 认定路径（存在生效的多码认定）：经 identity_core 把订单按「同一人」归一 ——
  按最早消费月重新分群、历史订单只在首次获客渠道计一次，再走同一套聚合落库。
撤销全部认定后自动回到原始路径，恢复原来的分群与渠道归属。

- 按首单月分群（cohorts.month = 会员首个订单月），群规模 N；
- M0 = 首单月（按定义全员活跃）；
- Mn = 该月有 ≥1 单的去重会员数 / N；
- 快照月尚未走到的月序标 right_censored，active=0、retention 为空，不参与拟合；
- 每个格子按渠道拆一份（channel=all 是矩阵汇总）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.constants import error_codes as codes
from src.constants.enums import COHORT_CHANNELS, CellState, IdentityStatus
from src.models.cohort import Cohort
from src.models.member_identity_link import MemberIdentityLink
from src.models.member_order import MemberOrder
from src.models.retention_cell import RetentionCell
from src.services import identity_core
from src.services.retention_core import CohortInput, build_retention_cells
from src.utils.errors import AppError
from src.utils.logger import get_logger

logger = get_logger("cohortltv.retention")


def _load_active_links(db: Session) -> list[MemberIdentityLink]:
    return list(
        db.execute(
            select(MemberIdentityLink).where(
                MemberIdentityLink.status == IdentityStatus.ACTIVE.value
            )
        ).scalars().all()
    )


def _raw_order_rows(db: Session) -> list[dict]:
    """全量订单事实（认定路径的唯一原料；24k 行级别可全量加载）。"""
    orders = db.execute(select(MemberOrder)).scalars().all()
    return [
        {
            "order_no": o.order_no,
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


def _persist_build(db: Session, cohorts: list[Cohort], build, now: datetime) -> None:
    """build_retention_cells 的结果整表落库（幂等），并回写各群规模与渠道构成。"""
    db.execute(delete(RetentionCell))
    cohort_ids = {str(cohort.id): cohort.id for cohort in cohorts}
    rows = [
        RetentionCell(
            cohort_id=cohort_ids[row["cohort_key"]],
            month_index=row["month_index"],
            channel=row["channel"],
            active_members=row["active_members"],
            sample_size=row["sample_size"],
            retention_rate=row["retention_rate"],
            revenue=row["revenue"],
            order_count=row["order_count"],
            right_censored=row["right_censored"],
            low_sample=row["low_sample"],
            updated_at=now,
        )
        for row in build.rows
    ]
    db.bulk_save_objects(rows)
    db.flush()

    for cohort in cohorts:
        cohort.rebuilt_at = now
        if cohort.channel_mix:
            mix = dict(cohort.channel_mix)
            for channel in COHORT_CHANNELS:
                entry = mix.get(channel) or {}
                entry["members"] = build.channel_members.get((cohort.month, channel), 0)
                mix[channel] = entry
            cohort.channel_mix = mix


def _rebuild_identity_aware(
    db: Session,
    cohorts: list[Cohort],
    links: list[MemberIdentityLink],
    snapshot: str,
    months: int,
) -> dict:
    """认定路径：订单按同一人归一后再聚合，群规模取有效去重人数。"""
    raw_orders = _raw_order_rows(db)
    person_map = identity_core.build_person_map([link.member_codes for link in links])
    resolved = identity_core.resolve_orders(raw_orders, person_map)
    channel_aggs, member_aggs = identity_core.aggregate_resolved(resolved)
    effective_sizes = identity_core.effective_cohort_sizes(resolved)

    build = build_retention_cells(
        [
            CohortInput(
                key=str(cohort.id),
                month=cohort.month,
                size=int(effective_sizes.get(cohort.month, 0)),
                channel_mix=cohort.channel_mix or {},
            )
            for cohort in cohorts
        ],
        channel_aggs,
        member_aggs,
        snapshot,
        months,
        settings.low_sample_threshold,
    )
    now = datetime.now(timezone.utc)
    _persist_build(db, cohorts, build, now)
    # 群规模回写为有效人数（被并走的群规模变小；空群为 0，保留群行不删）
    for cohort in cohorts:
        cohort.size = int(effective_sizes.get(cohort.month, 0))

    summary = {
        **build.summary,
        "rebuilt_at": now.isoformat(),
        "identity_mode": "merged",
        "active_links": len(links),
        "persons": sum(effective_sizes.values()),
    }
    logger.info("matrix rebuilt (identity merged) %s", summary)
    return summary


def rebuild_matrix(
    db: Session,
    snapshot_month: str | None = None,
    months: int | None = None,
) -> dict:
    snapshot = snapshot_month or settings.snapshot_month
    months = months or settings.matrix_months
    cohorts = db.execute(select(Cohort).order_by(Cohort.month)).scalars().all()
    if not cohorts:
        raise AppError(codes.MATRIX_EMPTY, "还没有同期群数据，无法重建矩阵")

    links = _load_active_links(db)
    if links:
        summary = _rebuild_identity_aware(db, cohorts, links, snapshot, months)
        db.commit()
        return summary

    channel_aggs = db.execute(
        select(
            MemberOrder.cohort_month,
            MemberOrder.month_index,
            MemberOrder.channel,
            func.count(distinct(MemberOrder.member_code)),
            func.sum(MemberOrder.amount),
            func.count(),
        ).group_by(MemberOrder.cohort_month, MemberOrder.month_index, MemberOrder.channel)
    ).all()

    member_aggs = db.execute(
        select(
            MemberOrder.cohort_month,
            MemberOrder.channel,
            func.count(distinct(MemberOrder.member_code)),
        ).group_by(MemberOrder.cohort_month, MemberOrder.channel)
    ).all()

    build = build_retention_cells(
        [
            CohortInput(
                key=str(cohort.id),
                month=cohort.month,
                size=int(cohort.size or 0),
                channel_mix=cohort.channel_mix or {},
            )
            for cohort in cohorts
        ],
        channel_aggs,
        member_aggs,
        snapshot,
        months,
        settings.low_sample_threshold,
    )

    # 矩阵是纯派生数据：整表重建（幂等）
    now = datetime.now(timezone.utc)
    _persist_build(db, cohorts, build, now)

    # 原始路径：群规模恢复为原始去重会员码数（撤销认定后回到原始分群）
    size_rows = db.execute(
        select(
            MemberOrder.cohort_month,
            func.count(distinct(MemberOrder.member_code)),
        ).group_by(MemberOrder.cohort_month)
    ).all()
    raw_sizes = {str(month): int(count) for month, count in size_rows}
    for cohort in cohorts:
        cohort.size = int(raw_sizes.get(cohort.month, cohort.size))

    db.commit()
    summary = {
        **build.summary,
        "rebuilt_at": now.isoformat(),
        "identity_mode": "raw",
        "active_links": 0,
    }
    logger.info("matrix rebuilt (raw) %s", summary)
    return summary


def cell_state(cell: RetentionCell) -> str:
    return CellState.RIGHT_CENSORED if cell.right_censored else CellState.OBSERVED
