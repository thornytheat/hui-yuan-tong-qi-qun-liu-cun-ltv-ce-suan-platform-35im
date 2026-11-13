"""一员多码认定的纯函数核心（无 ORM / Session 依赖，可直接 pytest）。

口径（与 README「认定口径」、后端服务、前端口径提示同源）：

1. 多会员码认定为同一人：并查集把若干组 member_code 合并，person_code 取组内字典序
   最小会员码（稳定、可复现）；同一认定重复执行产出的映射完全一致（幂等）。
2. 重新分群：一个人的首单月 = 其全部会员码全部订单的最早消费月（order_month 最小），
   该人整体归入该首单月同期群；订单的有效月序 = 相对新首单月的月差。
3. 渠道归属：历史订单只在该人的「首次获客渠道」计一次 —— 取最早消费月内最早一笔订单
   的渠道（is_first_order 优先，再按 ordered_at / channel 稳定兜底）。
4. 撤销 = 不应用任何认定组，原始 member_orders 的分群与渠道归属原样恢复。

本模块只吃普通 dict / dataclass，不做数据库读写；持久化与矩阵重建由 service 负责。
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from src.utils.months import month_span


# ---------------------------------------------------------------- 基础工具


def normalize_codes(codes: Iterable[str]) -> list[str]:
    """去重并稳定排序会员码；输入非字符串 / 空白会被剔除。"""
    cleaned = {str(code).strip() for code in codes if str(code).strip()}
    return sorted(cleaned)


def fingerprint(codes: Iterable[str]) -> str:
    """与模型 MemberIdentityLink.canonical_fingerprint 同算法（顺序无关）。"""
    return hashlib.sha256("|".join(normalize_codes(codes)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 并查集 / person 映射


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        # 路径压缩
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        self.add(a)
        self.add(b)
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # 字典序小者当根，保证 person_code 可复现
            if ra < rb:
                self.parent[rb] = ra
            else:
                self.parent[ra] = rb


def build_person_map(groups: Sequence[Sequence[str]]) -> dict[str, str]:
    """认定组 → {member_code: person_code}。

    空输入返回空映射（= 撤销后的原始状态）；组间有公共会员码会被并查集自动并成一人。
    """
    uf = _UnionFind()
    for group in groups:
        codes = normalize_codes(group)
        for code in codes:
            uf.add(code)
        for code in codes[1:]:
            uf.union(codes[0], code)
    return {code: uf.find(code) for code in uf.parent}


# ---------------------------------------------------------------- 订单归一


def _order_sort_key(order: Mapping) -> tuple[str, str, str]:
    return (
        str(order["order_month"]),
        str(order.get("ordered_at") or ""),
        str(order["channel"]),
    )


def person_first_attributes(
    raw_orders: Sequence[Mapping],
    person_map: Mapping[str, str],
) -> dict[str, tuple[str, str]]:
    """每个人的（最早消费月, 首次获客渠道）。

    最早消费月 = 该人全部订单的最小 order_month；
    首次获客渠道 = 最早消费月内最早一笔订单的渠道（is_first_order 标记优先）。
    """
    earliest: dict[str, Mapping] = {}
    person_orders: dict[str, list[Mapping]] = defaultdict(list)
    for order in raw_orders:
        person = person_map.get(str(order["member_code"]))
        if person is None:
            continue
        person_orders[person].append(order)
        prev = earliest.get(person)
        if prev is None or _order_sort_key(order) < _order_sort_key(prev):
            earliest[person] = order

    attrs: dict[str, tuple[str, str]] = {}
    for person, orders in person_orders.items():
        first_month = str(earliest[person]["order_month"])
        in_first = [o for o in orders if str(o["order_month"]) == first_month]
        flagged = [o for o in in_first if o.get("is_first_order")]
        pool = flagged or in_first
        first_order = min(pool, key=_order_sort_key)
        attrs[person] = (first_month, str(first_order["channel"]))
    return attrs


def resolve_orders(
    raw_orders: Sequence[Mapping],
    person_map: Mapping[str, str],
) -> list[dict]:
    """原始订单 → 认定口径订单（纯 dict，字段与 retention_core 的聚合输入对齐）。

    输出每笔订单带：
    - person_code        归属的人
    - cohort_month       有效首单月 = 该人最早消费月
    - channel            有效渠道 = 该人首次获客渠道（历史订单只在这里计一次）
    - month_index        有效月序 = 订单月相对有效首单月的月差（>=0）
    未出现在 person_map 的会员码按单人映射（code 即 person），口径自然回退到原始状态。
    """
    full_map: dict[str, str] = {str(o["member_code"]): str(o["member_code"]) for o in raw_orders}
    full_map.update(dict(person_map))
    attrs = person_first_attributes(raw_orders, full_map)

    resolved: list[dict] = []
    for order in raw_orders:
        member = str(order["member_code"])
        person = full_map[member]
        first_month, acquisition_channel = attrs[person]
        order_month = str(order["order_month"])
        resolved.append(
            {
                "member_code": member,
                "person_code": person,
                "cohort_month": first_month,
                "channel": acquisition_channel,
                "order_month": order_month,
                "month_index": month_span(first_month, order_month),
                "amount": float(order["amount"]),
                "is_first_order": bool(order.get("is_first_order", False)),
            }
        )
    return resolved


# ---------------------------------------------------------------- 聚合（喂 retention_core）


def raw_cohort_sizes(raw_orders: Sequence[Mapping]) -> dict[str, int]:
    """认定前：原始首单月 → 去重会员码数（= cohorts 表的原始规模口径）。"""
    members: dict[str, set[str]] = defaultdict(set)
    for order in raw_orders:
        members[str(order["cohort_month"])].add(str(order["member_code"]))
    return {month: len(codes) for month, codes in members.items()}


def effective_cohort_sizes(resolved: Sequence[Mapping]) -> dict[str, int]:
    """认定后：有效首单月 → 去重人数。"""
    persons: dict[str, set[str]] = defaultdict(set)
    for order in resolved:
        persons[str(order["cohort_month"])].add(str(order["person_code"]))
    return {month: len(persons) for month, persons in persons.items()}


def aggregate_resolved(
    resolved: Sequence[Mapping],
) -> tuple[list[tuple[str, int, str, int, float, int]], list[tuple[str, str, int]]]:
    """认定口径订单 → retention_core 需要的两种聚合。

    - channel_aggs: (cohort_month, month_index, channel, 去重人数, 营收合计, 订单数)
    - member_aggs : (cohort_month, channel, 去重人数) —— 群×渠道的真实人数（分母）
    """
    cell_persons: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    cell_revenue: dict[tuple[str, int, str], float] = defaultdict(float)
    cell_orders: dict[tuple[str, int, str], int] = defaultdict(int)
    mix_persons: dict[tuple[str, str], set[str]] = defaultdict(set)

    for order in resolved:
        cell_key = (
            str(order["cohort_month"]),
            int(order["month_index"]),
            str(order["channel"]),
        )
        cell_persons[cell_key].add(str(order["person_code"]))
        cell_revenue[cell_key] += float(order["amount"])
        cell_orders[cell_key] += 1
        mix_persons[(str(order["cohort_month"]), str(order["channel"]))].add(
            str(order["person_code"])
        )

    channel_aggs = [
        (month, m_idx, channel, len(persons), round(cell_revenue[(month, m_idx, channel)], 2),
         cell_orders[(month, m_idx, channel)])
        for (month, m_idx, channel), persons in sorted(cell_persons.items())
    ]
    member_aggs = [
        (month, channel, len(persons))
        for (month, channel), persons in sorted(mix_persons.items())
    ]
    return channel_aggs, member_aggs


# ---------------------------------------------------------------- 前后变化


def person_change_view(
    codes: Sequence[str],
    raw_orders: Sequence[Mapping],
    resolved: Sequence[Mapping],
) -> dict:
    """一个被认定的人：认定前（按码）→ 认定后（按人）的首单月 / 渠道变化。"""
    code_set = set(codes)
    before_codes = []
    for code in normalize_codes(codes):
        code_orders = [o for o in raw_orders if str(o["member_code"]) == code]
        if not code_orders:
            continue
        first = min(code_orders, key=_order_sort_key)
        before_codes.append(
            {
                "member_code": code,
                "first_order_month": str(first["cohort_month"]),
                "channel": str(first["channel"]),
                "orders": len(code_orders),
            }
        )

    person_orders = [o for o in resolved if str(o["person_code"]) in code_set]
    after = None
    if person_orders:
        first_month = min(str(o["cohort_month"]) for o in person_orders)
        after = {
            "person_code": str(person_orders[0]["person_code"]),
            "first_order_month": first_month,
            "channel": str(person_orders[0]["channel"]),
            "orders": len(person_orders),
        }

    before_months = sorted({row["first_order_month"] for row in before_codes})
    before_channels = sorted({row["channel"] for row in before_codes})
    # 是否存在会员码原来不在认定后的首单月群里（即有人被跨群挪动）
    moved = bool(after and any(month != after["first_order_month"] for month in before_months))
    return {
        "codes": before_codes,
        "before": {
            "first_order_months": before_months,
            "channels": before_channels,
        },
        "after": after,
        "moved_cohort": moved,
    }


__all__ = [
    "aggregate_resolved",
    "build_person_map",
    "effective_cohort_sizes",
    "fingerprint",
    "normalize_codes",
    "person_change_view",
    "person_first_attributes",
    "raw_cohort_sizes",
    "resolve_orders",
]
