"""Development-only PostgreSQL secret vault using AES-256-GCM ciphertext."""

import uuid

from sqlalchemy import select

from moallem.domain.authorization import require_tenant
from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import ActiveContext
from moallem.domain.secret_encryption import Aes256Gcm
from moallem.domain.secrets import SecretRef, SecretVault
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import SecretVaultEntryModel


class PostgresEncryptedVault(SecretVault):
    def __init__(self, sessions: SessionFactory, cipher: Aes256Gcm) -> None:
        self._sessions = sessions
        self._cipher = cipher

    def put(self, ctx: ActiveContext, raw: str) -> SecretRef:
        reference_id = uuid.uuid4()
        ciphertext = self._cipher.encrypt(
            raw, tenant_id=ctx.tenant_id, reference_id=str(reference_id)
        )
        with session_scope(self._sessions) as session:
            session.add(
                SecretVaultEntryModel(
                    tenant_id=uuid.UUID(ctx.tenant_id),
                    reference_id=reference_id,
                    ciphertext=ciphertext,
                    encryption_version="m1",
                )
            )
        return SecretRef(ctx.tenant_id, str(reference_id))

    def reveal(self, ctx: ActiveContext, ref: SecretRef) -> str:
        require_tenant(ctx, ref.tenant_id)
        try:
            tenant_id, reference_id = uuid.UUID(ctx.tenant_id), uuid.UUID(ref.ref_id)
        except ValueError as exc:
            raise ResourceNotFound("resource not found") from exc
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(SecretVaultEntryModel).where(
                    SecretVaultEntryModel.tenant_id == tenant_id,
                    SecretVaultEntryModel.reference_id == reference_id,
                )
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            ciphertext = row.ciphertext
        return self._cipher.decrypt(ciphertext, tenant_id=ctx.tenant_id, reference_id=ref.ref_id)

    def delete(self, ctx: ActiveContext, ref: SecretRef) -> None:
        self.reveal(ctx, ref)
        with session_scope(self._sessions) as session:
            row = session.scalar(
                select(SecretVaultEntryModel).where(
                    SecretVaultEntryModel.tenant_id == uuid.UUID(ctx.tenant_id),
                    SecretVaultEntryModel.reference_id == uuid.UUID(ref.ref_id),
                )
            )
            if row is None:
                raise ResourceNotFound("resource not found")
            session.delete(row)
