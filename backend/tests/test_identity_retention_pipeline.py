"""认定 → 留存矩阵的端到端口径（纯函数，不连库）。

证明 identity_core 的归一出参能直接喂给 retention_core，且认定 / 撤销两种状态下
矩阵规模、活跃数与渠道格符合「重新分群 + 渠道只计一次 + 撤销恢复」的要求。
"""
from __future__ import annotations

from src.services import identity_core as ic
from src.services.retention_core import CohortInput, build_retention_cells

SNAPSHOT = "2026-11"


def _orders() -> list[dict]:
    def o(member, cohort_month, channel, order_month, amount, first=False):
        return {
            "member_code": member,
            "cohort_month": cohort_month,
            "channel": channel,
            "order_month": order_month,
            "amount": amount,
            "is_first_order": first,
            "ordered_at": f"{order_month}-05T08:00:00+00:00",
        }

    return [
        o("s1", "2026-09", "store", "2026-09", 100.0, True),
        o("s1", "2026-09", "store", "2026-10", 50.0),
        o("p1", "2026-10", "private", "2026-10", 60.0, True),
        o("p1", "2026-10", "private", "2026-11", 20.0),
        o("f1", "2026-10", "paid_feed", "2026-10", 80.0, True),
    ]


def _build(orders, cohorts):
    channel_aggs, member_aggs = ic.aggregate_resolved(orders)
    sizes = ic.effective_cohort_sizes(orders)
    return build_retention_cells(
        [
            CohortInput(key=cid, month=month, size=sizes.get(month, 0))
            for cid, month in cohorts
        ],
        channel_aggs,
        member_aggs,
        SNAPSHOT,
        3,
        30,
    )


def test_merged_matrix_recohorts_and_single_channel() -> None:
    raw = _orders()
    person_map = ic.build_person_map([["s1", "p1"]])
    resolved = ic.resolve_orders(raw, person_map)
    build = _build(resolved, [("c9", "2026-09"), ("c10", "2026-10")])

    rows = {(r["cohort_key"], r["month_index"], r["channel"]): r for r in build.rows}
    # s1+p1 同一人归 2026-09 群：M0 活跃 1、M1（10 月）活跃 1，且渠道全部为 store
    assert rows[("c9", 0, "all")]["active_members"] == 1
    assert rows[("c9", 1, "all")]["active_members"] == 1
    assert rows[("c9", 0, "store")]["active_members"] == 1
    assert rows[("c9", 0, "private")]["active_members"] == 0
    # 2026-10 群只剩 f1 一人，且在 paid_feed
    assert rows[("c10", 0, "all")]["sample_size"] == 1
    assert rows[("c10", 0, "paid_feed")]["active_members"] == 1
    # 营收守恒
    assert sum(r["revenue"] for r in build.rows if r["channel"] == "all") == 310.0


def test_revoked_matrix_matches_raw_split() -> None:
    raw = _orders()
    resolved = ic.resolve_orders(raw, {})  # 撤销 → 原始归属
    build = _build(resolved, [("c9", "2026-09"), ("c10", "2026-10")])
    rows = {(r["cohort_key"], r["month_index"], r["channel"]): r for r in build.rows}

    # 原始：09 群 s1 一人 store；10 群 p1(private) + f1(paid_feed) 两人
    assert rows[("c9", 0, "store")]["active_members"] == 1
    assert rows[("c10", 0, "all")]["sample_size"] == 2
    assert rows[("c10", 0, "private")]["active_members"] == 1
    assert rows[("c10", 0, "paid_feed")]["active_members"] == 1


def test_repeated_merge_produces_identical_matrix() -> None:
    raw = _orders()
    first = ic.resolve_orders(raw, ic.build_person_map([["p1", "s1"]]))
    second = ic.resolve_orders(raw, ic.build_person_map([["s1", "p1"], ["s1", "p1"]]))
    assert ic.aggregate_resolved(first) == ic.aggregate_resolved(second)
    assert ic.effective_cohort_sizes(first) == ic.effective_cohort_sizes(second)
