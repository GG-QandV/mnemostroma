# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger("mnemostroma.gateway.outbox")

ObservationStatus = Literal["complete", "partial", "cancelled", "failed"]


async def ensure_gateway_schema(db: "aiosqlite.Connection") -> None:
    """Idempotent Gateway schema creation (ADR-006).

    Mirrors the pattern used by check_anchor_schema/check_session_schema
    in storage/sqlite.py — individual execute() calls per statement,
    each wrapped so a partial failure on one statement does not block
    the others. Always called from Conductor.start(), independent of
    gateway.enabled.
    """
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gateway_observer_outbox (
                event_id TEXT PRIMARY KEY,
                dedupe_key TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN (
                    'pending', 'processing', 'delivered', 'dead_letter'
                )),
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL,
                last_error_code TEXT,
                created_at INTEGER NOT NULL,
                delivered_at INTEGER
            )
        """)
        await db.commit()
    except Exception as e:
        logger.error(f"ensure_gateway_schema: outbox table failed: {e}")

    try:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_gateway_outbox_ready "
            "ON gateway_observer_outbox(state, next_attempt_at)"
        )
        await db.commit()
    except Exception as e:
        logger.error(f"ensure_gateway_schema: outbox index failed: {e}")

    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gateway_request_audit (
                request_id TEXT PRIMARY KEY,
                conversation_id_hash TEXT NOT NULL,
                client_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                protocol TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                model TEXT,
                memory_injected INTEGER NOT NULL,
                context_token_estimate INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                completed_at INTEGER
            )
        """)
        await db.commit()
    except Exception as e:
        logger.error(f"ensure_gateway_schema: audit table failed: {e}")

    try:
        await db.execute(
            "ALTER TABLE gateway_request_audit ADD COLUMN project_id TEXT"
        )
        await db.commit()
    except Exception:
        pass

    try:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_gateway_audit_created "
            "ON gateway_request_audit(created_at)"
        )
        await db.commit()
    except Exception as e:
        logger.error(f"ensure_gateway_schema: audit index failed: {e}")
    await db.commit()


@dataclass(frozen=True)
class ObservationEvent:
    event_id: str
    request_id: str
    conversation_id: str
    client_id: str
    project_id: str | None
    role: Literal["user", "assistant"]
    text: str
    status: ObservationStatus
    provider_id: str
    model: str
    created_at: float
    dedupe_key: str

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        conversation_id: str,
        client_id: str,
        project_id: str | None = None,
        role: Literal["user", "assistant"],
        text: str,
        status: ObservationStatus,
        provider_id: str,
        model: str,
        dedupe_key: str,
    ) -> "ObservationEvent":
        return cls(
            event_id=str(uuid.uuid4()),
            request_id=request_id,
            conversation_id=conversation_id,
            client_id=client_id,
            project_id=project_id,
            role=role,
            text=text,
            status=status,
            provider_id=provider_id,
            model=model,
            created_at=time.time(),
            dedupe_key=dedupe_key,
        )


class GatewayOutbox:
    """Durable SQLite-backed outbox for Observer bridge events."""

    def __init__(self, db: aiosqlite.Connection, *, max_attempts: int = 12) -> None:
        self._db = db
        self._max_attempts = max_attempts

    async def enqueue(self, event: ObservationEvent) -> None:
        payload = json.dumps({
            "event_id": event.event_id,
            "request_id": event.request_id,
            "conversation_id": event.conversation_id,
            "client_id": event.client_id,
            "project_id": event.project_id,
            "role": event.role,
            "text": event.text,
            "status": event.status,
            "provider_id": event.provider_id,
            "model": event.model,
            "created_at": event.created_at,
        })
        try:
            await self._db.execute(
                """
                INSERT INTO gateway_observer_outbox
                    (event_id, dedupe_key, payload_json, state,
                     attempts, next_attempt_at, created_at)
                VALUES (?, ?, ?, 'pending', 0, ?, ?)
                """,
                (event.event_id, event.dedupe_key, payload,
                 int(event.created_at), int(event.created_at)),
            )
            await self._db.commit()
        except Exception:
            await self._db.rollback()

    async def fetch_ready_batch(self, *, batch_size: int, now: int) -> list[dict]:
        cursor = await self._db.execute(
            """
            SELECT event_id, dedupe_key, payload_json, state,
                   attempts, next_attempt_at, last_error_code,
                   created_at, delivered_at
            FROM gateway_observer_outbox
            WHERE state = 'pending' AND next_attempt_at <= ?
            ORDER BY next_attempt_at ASC
            LIMIT ?
            """,
            (now, batch_size),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    async def mark_delivered(self, event_id: str) -> None:
        await self._db.execute(
            """
            UPDATE gateway_observer_outbox
            SET state = 'delivered', delivered_at = ?
            WHERE event_id = ?
            """,
            (int(time.time()), event_id),
        )
        await self._db.commit()

    async def mark_retry(self, event_id: str, *, error_code: str, backoff_sec: float) -> None:
        cursor = await self._db.execute(
            "SELECT attempts FROM gateway_observer_outbox WHERE event_id = ?",
            (event_id,),
        )
        row = await cursor.fetchone()
        attempts = (row[0] if row else 0) + 1
        next_state = "dead_letter" if attempts >= self._max_attempts else "pending"
        await self._db.execute(
            """
            UPDATE gateway_observer_outbox
            SET state = ?, attempts = ?, next_attempt_at = ?, last_error_code = ?
            WHERE event_id = ?
            """,
            (next_state, attempts, int(time.time() + backoff_sec), error_code, event_id),
        )
        await self._db.commit()

    async def record_audit(
        self,
        *,
        request_id: str,
        conversation_id: str,
        client_id: str,
        provider_id: str,
        model: str | None,
        project_id: str | None = None,
        memory_injected: bool,
        status: str,
        created_at: int,
        completed_at: int | None = None,
    ) -> None:
        import hashlib
        try:
            conv_hash = hashlib.sha256(conversation_id.encode()).hexdigest()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO gateway_request_audit
                    (request_id, conversation_id_hash, client_id, profile_id,
                     protocol, provider_id, model, project_id, memory_injected,
                     context_token_estimate, status, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id, conv_hash, client_id, provider_id,
                    "openai", provider_id, model, project_id, 1 if memory_injected else 0,
                    0, status, created_at, completed_at or int(time.time()),
                ),
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"audit write failed request_id={request_id}: {e}")

    async def cleanup_delivered(self, *, retention_hours: int) -> int:
        cutoff = int(time.time()) - retention_hours * 3600
        cursor = await self._db.execute(
            """
            DELETE FROM gateway_observer_outbox
            WHERE state = 'delivered' AND delivered_at < ?
            """,
            (cutoff,),
        )
        await self._db.commit()
        return cursor.rowcount
