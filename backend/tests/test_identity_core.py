"""一员多码认定（identity_core）单元测试：归一、重新分群、渠道只计一次、撤销恢复、幂等。

只测纯函数，不连数据库；手算小数据 + 守恒性质：
- 认定后按最早消费月重新分群；
- 历史订单只在首次获客渠道计一次；
- 撤销（空认定）恢复原始分群与渠道；
- 同一认定重复执行映射一致（幂等）。
"""
from __future__ import annotations

import pytest

from src.services import identity_core as ic


def _order(
    member: str,
    cohort_month: str,
    channel: str,
    order_month: str,
    amount: float,
    *,
    is_first: bool = False,
    ordered_at: str = "",
) -> dict:
    return {
        "member_code": member,
        "cohort_month": cohort_month,
        "channel": channel,
        "order_month": order_month,
        "amount": amount,
        "is_first_order": is_first,
        "ordered_at": ordered_at or f"{order_month}-05T08:00:00+00:00",
    }


def _small_orders() -> list[dict]:
    # A 有两个会员码：门店首单 2026-09（store），私域首单 2026-10（private）
    return [
        _order("A-store", "2026-09", "store", "2026-09", 100.0, is_first=True,
               ordered_at="2026-09-02T08:00:00+00:00"),
        _order("A-store", "2026-09", "store", "2026-10", 40.0,
               ordered_at="2026-10-03T08:00:00+00:00"),
        _order("A-private", "2026-10", "private", "2026-10", 60.0, is_first=True,
               ordered_at="2026-10-04T08:00:00+00:00"),
        _order("A-private", "2026-10", "private", "2026-11", 20.0,
               ordered_at="2026-11-05T08:00:00+00:00"),
        # B 单人，信息流，2026-10 首单
        _order("B-feed", "2026-10", "paid_feed", "2026-10", 80.0, is_first=True,
               ordered_at="2026-10-06T08:00:00+00:00"),
    ]


# ---------------------------------------------------------------- 并查集 / 映射


def test_build_person_map_merges_and_picks_lexicographic_root() -> None:
    person_map = ic.build_person_map([["A-private", "A-store"]])
    assert person_map == {"A-private": "A-private", "A-store": "A-private"}


def test_build_person_map_is_order_independent_and_idempotent() -> None:
    first = ic.build_person_map([["A-store", "A-private"]])
    second = ic.build_person_map([["A-private", "A-store", "A-private"]])  # 含重复
    assert first == second
    # 同一认定重复执行 → 完全一致
    assert ic.build_person_map([["A-store", "A-private"]]) == first


def test_build_person_map_transitive_groups_union() -> None:
    person_map = ic.build_person_map([["a", "b"], ["b", "c"]])
    assert set(person_map.values()) == {"a"}


def test_build_person_map_empty_is_revoke_state() -> None:
    assert ic.build_person_map([]) == {}


def test_fingerprint_order_independent() -> None:
    assert ic.fingerprint(["x", "y"]) == ic.fingerprint(["y", "x", "x"])


# ---------------------------------------------------------------- 重新分群 / 渠道归因


def test_resolve_orders_recohort_to_earliest_month_and_single_channel() -> None:
    orders = _small_orders()
    person_map = ic.build_person_map([["A-store", "A-private"]])
    resolved = ic.resolve_orders(orders, person_map)

    a_rows = [r for r in resolved if r["person_code"] == "A-private"]
    # 全部归入最早消费月 2026-09
    assert {r["cohort_month"] for r in a_rows} == {"2026-09"}
    # 历史订单只在首次获客渠道（store）计一次
    assert {r["channel"] for r in a_rows} == {"store"}
    # 有效月序相对新首单月
    by_month = {r["order_month"]: r["month_index"] for r in a_rows}
    assert by_month == {"2026-09": 0, "2026-10": 1, "2026-11": 2}

    # 未认定的 B 保持原始口径
    b_rows = [r for r in resolved if r["person_code"] == "B-feed"]
    assert len(b_rows) == 1
    assert b_rows[0]["cohort_month"] == "2026-10"
    assert b_rows[0]["channel"] == "paid_feed"


def test_first_acquisition_channel_uses_earliest_order() -> None:
    # 首单月内多笔、多渠道：取最早一笔（is_first_order 优先）
    orders = [
        _order("c1", "2026-08", "private", "2026-08", 10.0,
               ordered_at="2026-08-20T08:00:00+00:00"),
        _order("c1", "2026-08", "store", "2026-08", 20.0, is_first=True,
               ordered_at="2026-08-01T08:00:00+00:00"),
        _order("c2", "2026-09", "paid_feed", "2026-09", 30.0, is_first=True),
    ]
    person_map = ic.build_person_map([["c1", "c2"]])
    resolved = ic.resolve_orders(orders, person_map)
    assert {r["cohort_month"] for r in resolved} == {"2026-08"}
    assert {r["channel"] for r in resolved} == {"store"}


def test_resolve_orders_no_links_equals_raw_attribution() -> None:
    orders = _small_orders()
    resolved = ic.resolve_orders(orders, {})
    for raw, out in zip(orders, resolved):
        assert out["cohort_month"] == raw["cohort_month"]
        assert out["channel"] == raw["channel"]
        assert out["person_code"] == raw["member_code"]


# ---------------------------------------------------------------- 聚合 / 规模


def test_effective_and_raw_cohort_sizes() -> None:
    orders = _small_orders()
    raw_sizes = ic.raw_cohort_sizes(orders)
    assert raw_sizes == {"2026-09": 1, "2026-10": 2}  # A 两个码 + B，拆成 2 群共 3 码

    person_map = ic.build_person_map([["A-store", "A-private"]])
    resolved = ic.resolve_orders(orders, person_map)
    sizes = ic.effective_cohort_sizes(resolved)
    # A 合并后整体回到 2026-09 群：09 群 1 人、10 群只剩 B 1 人，总人数 2
    assert sizes == {"2026-09": 1, "2026-10": 1}


def test_aggregate_resolved_dedupes_persons_and_conserves_revenue() -> None:
    orders = _small_orders()
    person_map = ic.build_person_map([["A-store", "A-private"]])
    resolved = ic.resolve_orders(orders, person_map)
    channel_aggs, member_aggs = ic.aggregate_resolved(resolved)

    total_revenue = sum(row[4] for row in channel_aggs)
    assert total_revenue == pytest.approx(sum(o["amount"] for o in orders))
    total_orders = sum(row[5] for row in channel_aggs)
    assert total_orders == len(orders)

    # 群×渠道分母（去重人数）：A 的 store 群 1 人；B 的 paid_feed 群 1 人
    mix = {(month, channel): members for month, channel, members in member_aggs}
    assert mix[("2026-09", "store")] == 1
    assert mix[("2026-10", "paid_feed")] == 1
    # private 渠道在认定后不再承接 A 的任何订单
    assert all(channel != "private" for _, _, channel, *_ in channel_aggs)


# ---------------------------------------------------------------- 撤销 / 前后变化


def test_revoke_restores_original_split_and_channel() -> None:
    orders = _small_orders()
    person_map = ic.build_person_map([["A-store", "A-private"]])
    merged = ic.resolve_orders(orders, person_map)
    revoked = ic.resolve_orders(orders, {})  # 撤销 = 空认定

    assert ic.effective_cohort_sizes(merged) == {"2026-09": 1, "2026-10": 1}
    assert ic.effective_cohort_sizes(revoked) == ic.raw_cohort_sizes(orders)
    # 撤销后 A-private 的订单重新归 private / 2026-10
    restored = [r for r in revoked if r["member_code"] == "A-private"]
    assert {r["channel"] for r in restored} == {"private"}
    assert {r["cohort_month"] for r in restored} == {"2026-10"}


def test_person_change_view_reports_before_after() -> None:
    orders = _small_orders()
    person_map = ic.build_person_map([["A-store", "A-private"]])
    resolved = ic.resolve_orders(orders, person_map)
    view = ic.person_change_view(["A-store", "A-private"], orders, resolved)

    assert {c["member_code"] for c in view["codes"]} == {"A-store", "A-private"}
    assert view["before"]["first_order_months"] == ["2026-09", "2026-10"]
    assert view["after"]["first_order_month"] == "2026-09"
    assert view["after"]["channel"] == "store"
    assert view["moved_cohort"] is True


def test_total_persons_never_exceeds_raw_codes() -> None:
    orders = _small_orders()
    person_map = ic.build_person_map([["A-store", "A-private"]])
    resolved = ic.resolve_orders(orders, person_map)
    merged_total = sum(ic.effective_cohort_sizes(resolved).values())
    raw_total = sum(ic.raw_cohort_sizes(orders).values())
    assert merged_total == raw_total - 1  # 3 个码 → 2 个人
    assert merged_total <= raw_total
