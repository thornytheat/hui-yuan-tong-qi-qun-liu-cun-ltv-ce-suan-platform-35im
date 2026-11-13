from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.controllers import identity_controller
from src.middlewares.rate_limit import rate_limit
from src.middlewares.rbac import require_permission
from src.models.user import User
from src.schemas.identity import (
    IdentityActionOut,
    IdentityListOut,
    IdentityMergeRequest,
    IdentityOverviewOut,
)

router = APIRouter(prefix="/identity", tags=["identity"])


@router.get("/overview", response_model=IdentityOverviewOut)
def overview(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("identity:read")),
) -> dict:
    return identity_controller.overview(db)


@router.get("/links", response_model=IdentityListOut)
def list_links(
    status: str | None = Query(default=None, pattern="^(active|revoked)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("identity:read")),
) -> dict:
    return identity_controller.list_links(db, status)


@router.post("/links", response_model=IdentityActionOut)
def merge_codes(
    payload: IdentityMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("identity:write")),
    _: None = rate_limit("rebuild"),
) -> dict:
    return identity_controller.merge(db, payload, user, request)


@router.post("/links/{link_id}/revoke", response_model=IdentityActionOut)
def revoke_link(
    link_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("identity:write")),
    _: None = rate_limit("rebuild"),
) -> dict:
    return identity_controller.revoke(db, link_id, user, request)
