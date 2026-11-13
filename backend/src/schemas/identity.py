"""一员多码认定的对外 schema。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class IdentityMergeRequest(BaseModel):
    member_codes: list[str] = Field(
        description="要认定为同一人的会员码（至少 2 个，顺序无关、自动去重）",
        min_length=2,
        max_length=50,
    )
    note: str = Field(default="", max_length=400)


class IdentityLinkOut(BaseModel):
    id: str
    person_code: str
    member_codes: list[str]
    code_count: int
    status: Literal["active", "revoked"]
    fingerprint: str
    first_order_month: str | None = None
    first_channel: str | None = None
    note: str = ""
    created_by: str = ""
    revoked_by: str = ""
    created_at: str
    revoked_at: str | None = None


class CohortSizeChange(BaseModel):
    cohort_month: str
    before: int
    after: int
    delta: int


class IdentityChangeOut(BaseModel):
    members_before: int
    members_after: int
    cohort_size_changes: list[CohortSizeChange]
    persons: list[dict[str, Any]]


class IdentityActionOut(BaseModel):
    idempotent: bool
    applied: bool | None = None
    revoked: bool | None = None
    link: IdentityLinkOut
    rebuild: dict[str, Any] | None = None
    change: IdentityChangeOut | None = None
    change_before: IdentityChangeOut | None = None


class IdentityListOut(BaseModel):
    total: int
    items: list[IdentityLinkOut]


class IdentityOverviewOut(BaseModel):
    active_links: int
    revoked_links: int
    members_raw: int
    members_effective: int
    members_before: int
    members_after: int
    identity_mode: Literal["raw", "merged"]
    cohort_sizes: list[dict[str, Any]]
