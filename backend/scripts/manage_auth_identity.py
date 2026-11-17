#!/usr/bin/env python3
"""Provision or suspend Moallem identities from a trusted operator environment.

This command intentionally is not an HTTP endpoint. Unknown Auth0 subjects are never
provisioned by an API login, and role assignment is limited to TEACHER until DEC-027
(the formal permission matrix) receives product/security approval.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Sequence
from urllib.parse import urlsplit

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from moallem.persistence.database import sqlalchemy_url
from moallem.persistence.models import MembershipModel, TenantModel, UserModel

ALLOWED_INITIAL_ROLES = {"TEACHER"}
USER_STATUSES = {"ACTIVE", "SUSPENDED", "REVOKED"}


def _uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValueError(f"{field} must be a UUID") from None


def _sessions() -> tuple[Engine, sessionmaker[Session]]:
    raw_url = os.environ.get("MOALLEM_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("MOALLEM_DATABASE_URL is required")
    engine = create_engine(sqlalchemy_url(raw_url), pool_pre_ping=True, hide_parameters=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


def provision(args: argparse.Namespace, sessions: sessionmaker[Session]) -> None:
    issuer = args.issuer
    subject = args.subject
    issuer_parts = urlsplit(issuer)
    if (
        issuer_parts.scheme != "https"
        or not issuer_parts.hostname
        or issuer_parts.username is not None
        or issuer_parts.password is not None
        or issuer_parts.path not in ("", "/")
        or issuer_parts.query
        or issuer_parts.fragment
        or not issuer.endswith("/")
    ):
        raise ValueError("issuer must be the exact HTTPS Auth0 issuer ending in /")
    if not subject or subject != subject.strip() or len(subject) > 512:
        raise ValueError("subject must be 1..512 exact characters without surrounding whitespace")
    if args.role not in ALLOWED_INITIAL_ROLES:
        raise ValueError("only TEACHER can be provisioned until the permission matrix is approved")

    user_id = _uuid(args.user_id, "user_id")
    tenant_id = _uuid(args.tenant_id, "tenant_id")
    membership_id = _uuid(args.membership_id, "membership_id")

    with sessions.begin() as session:
        tenant = session.get(TenantModel, tenant_id)
        if tenant is None:
            if not args.tenant_name:
                raise ValueError("tenant does not exist; pass --tenant-name to create it")
            session.add(TenantModel(id=tenant_id, name=args.tenant_name))
            session.flush()

        user = session.scalar(
            select(UserModel).where(
                UserModel.auth_issuer == issuer,
                UserModel.auth_subject == subject,
            )
        )
        if user is None:
            user = session.get(UserModel, user_id)
            if user is not None:
                raise ValueError("user_id already belongs to another identity")
            user = UserModel(
                id=user_id,
                auth_issuer=issuer,
                auth_subject=subject,
                auth_status="ACTIVE",
            )
            session.add(user)
            session.flush()
        elif user.id != user_id:
            raise ValueError("Auth0 subject is already linked to a different user_id")
        elif user.auth_status != "ACTIVE":
            raise ValueError("identity is not ACTIVE; explicitly reactivate it before provisioning")

        existing_membership = session.scalar(
            select(MembershipModel).where(
                MembershipModel.user_id == user.id,
                MembershipModel.tenant_id == tenant_id,
            )
        )
        if existing_membership is not None:
            raise ValueError("user already has a membership in this tenant")
        if session.get(MembershipModel, membership_id) is not None:
            raise ValueError("membership_id already exists")
        session.add(
            MembershipModel(
                id=membership_id,
                user_id=user.id,
                tenant_id=tenant_id,
                roles=[args.role],
                status="ACTIVE",
            )
        )

    print(f"Provisioned user_id={user_id} tenant_id={tenant_id} membership_id={membership_id}")


def set_status(args: argparse.Namespace, sessions: sessionmaker[Session]) -> None:
    user_id = _uuid(args.user_id, "user_id")
    if args.status not in USER_STATUSES:
        raise ValueError("status must be ACTIVE, SUSPENDED, or REVOKED")
    with sessions.begin() as session:
        user = session.get(UserModel, user_id)
        if user is None:
            raise ValueError("user not found")
        if user.auth_status == "REVOKED" and args.status != "REVOKED":
            raise ValueError("REVOKED identities are terminal; create a new identity mapping")
        user.auth_status = args.status
    print(f"Updated user_id={user_id} auth_status={args.status}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("provision", help="create an Auth0 mapping and TEACHER membership")
    create.add_argument("--issuer", required=True)
    create.add_argument("--subject", required=True, help="Auth0 sub claim; never logged or echoed")
    create.add_argument("--user-id", required=True)
    create.add_argument("--tenant-id", required=True)
    create.add_argument("--tenant-name")
    create.add_argument("--membership-id", required=True)
    create.add_argument("--role", choices=sorted(ALLOWED_INITIAL_ROLES), default="TEACHER")
    status = commands.add_parser("set-status", help="activate, suspend, or revoke an account")
    status.add_argument("--user-id", required=True)
    status.add_argument("--status", choices=sorted(USER_STATUSES), required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    engine, sessions = _sessions()
    try:
        if args.command == "provision":
            provision(args, sessions)
        else:
            set_status(args, sessions)
    except Exception as exc:
        # Never print SQL parameters or the Auth0 subject/token, which may appear in input errors.
        print(f"identity operation failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
