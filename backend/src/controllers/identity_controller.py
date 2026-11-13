"""一员多码认定：认定 / 撤销 / 列表 / 总览（编排 + 审计 + 限流）。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.constants.templates import ACTION_IDENTITY_MERGE, ACTION_IDENTITY_REVOKE
from src.models.user import User
from src.services import audit_service, identity_service


def merge(db: Session, payload, user: User, request: Request) -> dict:
    result = identity_service.apply_link(db, payload.member_codes, payload.note, user)
    if not result["idempotent"]:
        link = result["link"]
        audit_service.record(
            db,
            ACTION_IDENTITY_MERGE,
            user=user,
            entity="identity_link",
            entity_id=str(link["id"]),
            detail=f"codes={link['code_count']} person={link['person_code']} "
            f"first_month={link['first_order_month']} channel={link['first_channel']}",
            request=request,
        )
        db.commit()
    return result


def revoke(db: Session, link_id: str, user: User, request: Request) -> dict:
    result = identity_service.revoke_link(db, link_id, user)
    link = result["link"]
    audit_service.record(
        db,
        ACTION_IDENTITY_REVOKE,
        user=user,
        entity="identity_link",
        entity_id=str(link["id"]),
        detail=f"revoke person={link['person_code']} codes={link['code_count']}",
        request=request,
    )
    db.commit()
    return result


def list_links(db: Session, status: str | None) -> dict:
    return identity_service.list_links(db, status)


def overview(db: Session) -> dict:
    return identity_service.overview(db)
