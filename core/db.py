"""
Database layer — asyncpg + Neon PostgreSQL.
Центральний інтерфейс для всіх агентів.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def _get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db.init() не було викликано")
    return _pool


async def _setup_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


_DDL = """
CREATE TABLE IF NOT EXISTS dialogs (
    id          SERIAL PRIMARY KEY,
    client_id   VARCHAR(50)  NOT NULL DEFAULT 'etalhome',
    user_id     VARCHAR(50)  NOT NULL,
    source      VARCHAR(20)  NOT NULL,
    messages    JSONB        DEFAULT '[]',
    updated_at  TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (client_id, user_id, source)
);
CREATE INDEX IF NOT EXISTS idx_dialogs_messages_gin ON dialogs USING GIN (messages);

CREATE TABLE IF NOT EXISTS trainer_suggestions (
    id          SERIAL PRIMARY KEY,
    client_id   VARCHAR(50)  NOT NULL DEFAULT 'etalhome',
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    type        TEXT,
    priority    TEXT,
    problem     TEXT,
    suggestion  TEXT,
    status      TEXT DEFAULT 'new'
);

CREATE TABLE IF NOT EXISTS analysis_history (
    id                  SERIAL PRIMARY KEY,
    client_id           TEXT         NOT NULL DEFAULT 'default',
    kind                TEXT         NOT NULL,
    confidence          TEXT         NOT NULL DEFAULT 'середня',
    source_tg_file_id   TEXT,
    source_tg_msg_id    BIGINT,
    report_text         TEXT,
    metadata            JSONB        DEFAULT '{}',
    created_at          TIMESTAMPTZ  DEFAULT NOW()
);
ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_analysis_client_created ON analysis_history(client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_metadata_gin ON analysis_history USING GIN (metadata);

CREATE TABLE IF NOT EXISTS design_history (
    id           SERIAL PRIMARY KEY,
    client_id    TEXT         NOT NULL DEFAULT 'default',
    source       TEXT         NOT NULL,
    mode         TEXT         NOT NULL,
    dir_path     TEXT         NOT NULL,
    generated_at TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_design_history_client ON design_history(client_id, generated_at DESC);

CREATE TABLE IF NOT EXISTS fix_history (
    id           SERIAL PRIMARY KEY,
    client_id    TEXT         NOT NULL DEFAULT 'default',
    url          TEXT         NOT NULL,
    fix_count    INTEGER,
    fix_path     TEXT,
    backup_path  TEXT,
    status       TEXT         NOT NULL DEFAULT 'generated',
    pr_url       TEXT,
    score_before INTEGER,
    score_after  INTEGER,
    generated_at TIMESTAMPTZ  DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fix_history_client_url ON fix_history(client_id, url, generated_at DESC);

CREATE TABLE IF NOT EXISTS session_state (
    id           SERIAL PRIMARY KEY,
    client_id    VARCHAR(50)  NOT NULL,
    user_id      VARCHAR(50)  NOT NULL,
    source       VARCHAR(20)  NOT NULL,
    active_agent TEXT,
    awaiting     TEXT,
    payload      JSONB        DEFAULT '{}',
    updated_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (client_id, user_id, source)
);

CREATE TABLE IF NOT EXISTS agent_prompts (
    id                   SERIAL PRIMARY KEY,
    client_id            TEXT NOT NULL,
    agent_id             TEXT NOT NULL,
    prompt_text          TEXT NOT NULL,
    version              INT  NOT NULL DEFAULT 1,
    previous_prompt_text TEXT,
    previous_version     INT,
    updated_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_by           TEXT DEFAULT 'system',
    UNIQUE(client_id, agent_id)
);

CREATE TABLE IF NOT EXISTS orchestrator_pending_review (
    id               SERIAL PRIMARY KEY,
    client_id        TEXT NOT NULL,
    issues_summary   TEXT NOT NULL,
    change_log       TEXT NOT NULL DEFAULT '[]',
    new_prompt       TEXT NOT NULL,
    dialogs_analyzed INT,
    dialogs_from     TIMESTAMPTZ,
    dialogs_to       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id)
);
"""


async def init() -> None:
    global _pool
    from pathlib import Path
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL не знайдено в env")
    _pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=4,
        init=_setup_conn,
    )
    async with _pool.acquire() as conn:
        await conn.execute(_DDL)
        # Auto-seed orchestrator.md into agent_prompts if not yet seeded
        client_id = os.getenv("DEFAULT_CLIENT_ID", "etalhome")
        exists = await conn.fetchval(
            "SELECT 1 FROM agent_prompts WHERE client_id=$1 AND agent_id='orchestrator' LIMIT 1",
            client_id,
        )
        if not exists:
            prompt_path = Path(__file__).parent.parent / "agents" / "orchestrator.md"
            if prompt_path.exists():
                prompt = prompt_path.read_text(encoding="utf-8").strip()
                await conn.execute(
                    "INSERT INTO agent_prompts (client_id, agent_id, prompt_text, version, updated_by) "
                    "VALUES ($1, 'orchestrator', $2, 1, 'seed')",
                    client_id, prompt,
                )
                logger.info("[db] Auto-seeded agents/orchestrator.md → agent_prompts v1")
    logger.info("[db] pool ready")


async def close() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def check_connection(retries: int = 3, delay: float = 2.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            pool = _get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            logger.info("[db] check_connection OK")
            return True
        except Exception as e:
            logger.warning("[db] check_connection attempt %d/%d: %s", attempt, retries, e)
            if attempt < retries:
                await asyncio.sleep(delay)
    return False


# ── Dialogs ───────────────────────────────────────────────────────────────────

async def save_message(
    client_id: str,
    user_id: str,
    source: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> None:
    new_msg = {
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta": meta or {},
    }
    pool = _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT messages FROM dialogs "
                "WHERE client_id=$1 AND user_id=$2 AND source=$3 FOR UPDATE",
                client_id, user_id, source,
            )
            if row is None:
                messages: list = [new_msg]
            else:
                messages = list(row["messages"])
                messages.append(new_msg)
                if len(messages) > 50:
                    messages = messages[-50:]
            await conn.execute(
                """INSERT INTO dialogs (client_id, user_id, source, messages)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (client_id, user_id, source) DO UPDATE SET
                       messages   = $4,
                       updated_at = NOW()""",
                client_id, user_id, source, messages,
            )


async def load_history(
    client_id: str,
    user_id: str,
    source: str,
    limit: int = 8,
) -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT messages FROM dialogs WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )
    if row is None:
        return []
    return list(row["messages"])[-limit:]


# ── Review / Stats ────────────────────────────────────────────────────────────

async def get_dialogs_review(
    client_id: str,
    limit: int = 30,
    only_low: bool = False,
) -> list[dict]:
    """Пари user/assistant з meta для Trainer і /review."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT messages FROM dialogs WHERE client_id=$1 ORDER BY updated_at DESC",
            client_id,
        )
    pairs: list[dict] = []
    for row in rows:
        msgs = list(row["messages"])
        for i in range(0, len(msgs) - 1, 2):
            u, a = msgs[i], msgs[i + 1]
            if u.get("role") != "user" or a.get("role") != "assistant":
                continue
            meta = a.get("meta") or {}
            confidence = float(meta.get("confidence", 0.9))
            needs_human = bool(meta.get("needs_human", False))
            if only_low and confidence >= 0.75 and not needs_human:
                continue
            pairs.append({
                "user_msg": u["content"],
                "bot_reply": a["content"],
                "confidence": confidence,
                "needs_human": needs_human,
                "created_at": u.get("ts", ""),
            })
        if len(pairs) >= limit:
            break
    return pairs[:limit]


async def get_dialogs_stats(client_id: str) -> dict:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT messages FROM dialogs WHERE client_id=$1",
            client_id,
        )
    total = 0
    conf_sum = 0.0
    escalations = 0
    cost_sum = 0.0
    for row in rows:
        for msg in row["messages"]:
            if msg.get("role") != "assistant":
                continue
            meta = msg.get("meta") or {}
            total += 1
            conf_sum += float(meta.get("confidence", 0.9))
            if meta.get("needs_human"):
                escalations += 1
            cost_sum += float(meta.get("cost_usd", 0.0))
    return {
        "total": total,
        "avg_confidence": round(conf_sum / total, 2) if total else 0.0,
        "escalations": escalations,
        "total_cost": round(cost_sum, 4),
    }


# ── Trainer suggestions ───────────────────────────────────────────────────────

async def save_trainer_suggestion(
    client_id: str,
    type: str,
    priority: str,
    problem: str,
    suggestion: str,
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO trainer_suggestions (client_id, type, priority, problem, suggestion)
               VALUES ($1, $2, $3, $4, $5)""",
            client_id, type, priority, problem, suggestion,
        )


async def list_trainer_suggestions(client_id: str, status: str = "new") -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM trainer_suggestions WHERE client_id=$1 AND status=$2 ORDER BY created_at DESC",
            client_id, status,
        )
    return [dict(r) for r in rows]


# ── Analysis history ──────────────────────────────────────────────────────────

async def save_analysis(
    client_id: str,
    kind: str,
    confidence: str,
    report_text: str = "",
    source_tg_file_id: str = "",
    source_tg_msg_id: int = 0,
    metadata: dict | None = None,
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO analysis_history
               (client_id, kind, confidence, source_tg_file_id, source_tg_msg_id, report_text, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            client_id, kind, confidence,
            source_tg_file_id or None,
            source_tg_msg_id or None,
            report_text,
            metadata or {},
        )


# ── Session state ─────────────────────────────────────────────────────────────

_SESSION_TTL_MINUTES = 30


async def get_session_state(
    client_id: str,
    user_id: str,
    source: str,
) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT active_agent, awaiting, payload, updated_at FROM session_state "
            "WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )
    if row is None:
        return None
    # Автоматичне очищення після TTL
    from datetime import timezone
    age = datetime.now(timezone.utc) - row["updated_at"].replace(tzinfo=timezone.utc)
    if age.total_seconds() > _SESSION_TTL_MINUTES * 60:
        await clear_session_state(client_id, user_id, source)
        return None
    return {"active_agent": row["active_agent"], "awaiting": row["awaiting"], "payload": row["payload"]}


async def set_session_state(
    client_id: str,
    user_id: str,
    source: str,
    active_agent: str,
    awaiting: str | None = None,
    payload: dict | None = None,
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO session_state (client_id, user_id, source, active_agent, awaiting, payload)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (client_id, user_id, source) DO UPDATE SET
                   active_agent = $4,
                   awaiting     = $5,
                   payload      = $6,
                   updated_at   = NOW()""",
            client_id, user_id, source, active_agent, awaiting, payload or {},
        )


async def clear_session_state(
    client_id: str,
    user_id: str,
    source: str,
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM session_state WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )


# ── Agent prompts (versioned, trainer-managed) ───────────────────────────────

async def get_agent_prompt(client_id: str, agent_id: str) -> str | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT prompt_text FROM agent_prompts WHERE client_id=$1 AND agent_id=$2",
            client_id, agent_id,
        )
    return row["prompt_text"] if row else None


async def save_agent_prompt(client_id: str, agent_id: str, prompt_text: str, updated_by: str) -> int:
    """UPSERT with versioning. Returns new version number."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO agent_prompts (client_id, agent_id, prompt_text, version, updated_by)
               VALUES ($1, $2, $3, 1, $4)
               ON CONFLICT (client_id, agent_id) DO UPDATE SET
                 previous_prompt_text = agent_prompts.prompt_text,
                 previous_version     = agent_prompts.version,
                 prompt_text          = EXCLUDED.prompt_text,
                 version              = agent_prompts.version + 1,
                 updated_at           = NOW(),
                 updated_by           = EXCLUDED.updated_by
               RETURNING version""",
            client_id, agent_id, prompt_text, updated_by,
        )
    return row["version"]


async def rollback_agent_prompt(client_id: str, agent_id: str) -> int | None:
    """Swap prompt_text ↔ previous_prompt_text. Returns restored version or None."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE agent_prompts SET
                 prompt_text          = previous_prompt_text,
                 version              = previous_version,
                 previous_prompt_text = NULL,
                 previous_version     = NULL,
                 updated_at           = NOW(),
                 updated_by           = 'rollback'
               WHERE client_id=$1 AND agent_id=$2 AND previous_prompt_text IS NOT NULL
               RETURNING version""",
            client_id, agent_id,
        )
    return row["version"] if row else None


# ── Orchestrator pending review ───────────────────────────────────────────────

async def save_pending_review(
    client_id: str,
    issues: str,
    new_prompt: str,
    change_log: str,
    dialogs_count: int,
    dialogs_from: datetime,
    dialogs_to: datetime,
) -> int:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO orchestrator_pending_review
                 (client_id, issues_summary, new_prompt, change_log,
                  dialogs_analyzed, dialogs_from, dialogs_to)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (client_id) DO UPDATE SET
                 issues_summary   = EXCLUDED.issues_summary,
                 new_prompt       = EXCLUDED.new_prompt,
                 change_log       = EXCLUDED.change_log,
                 dialogs_analyzed = EXCLUDED.dialogs_analyzed,
                 dialogs_from     = EXCLUDED.dialogs_from,
                 dialogs_to       = EXCLUDED.dialogs_to,
                 created_at       = NOW()
               RETURNING id""",
            client_id, issues, new_prompt, change_log,
            dialogs_count, dialogs_from, dialogs_to,
        )
    return row["id"]


async def get_pending_review(client_id: str) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orchestrator_pending_review WHERE client_id=$1",
            client_id,
        )
    return dict(row) if row else None


async def clear_pending_review(client_id: str) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM orchestrator_pending_review WHERE client_id=$1",
            client_id,
        )


# ── Analysis history ──────────────────────────────────────────────────────────

# ── Fix history (Neon) ────────────────────────────────────────────────────────

async def save_fix(
    client_id: str,
    url: str,
    fix_count: int,
    fix_path: str,
    score_before: int | None = None,
) -> int:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO fix_history (client_id, url, fix_count, fix_path, score_before)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            client_id, url, fix_count, fix_path, score_before,
        )
    logger.info("[db] Fix збережено: %s fix_count=%d", url, fix_count)
    return row["id"]


async def update_fix_status(
    fix_id: int,
    status: str,
    pr_url: str | None = None,
    score_after: int | None = None,
    backup_path: str | None = None,
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE fix_history
               SET status=$2,
                   pr_url=COALESCE($3, pr_url),
                   score_after=COALESCE($4, score_after),
                   backup_path=COALESCE($5, backup_path),
                   updated_at=NOW()
               WHERE id=$1""",
            fix_id, status, pr_url, score_after, backup_path,
        )
    logger.info("[db] Fix #%d статус: %s", fix_id, status)


async def get_any_last_fix(client_id: str) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM fix_history WHERE client_id=$1 ORDER BY generated_at DESC LIMIT 1",
            client_id,
        )
    return dict(row) if row else None


async def get_last_fix(client_id: str, url: str) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM fix_history
               WHERE client_id=$1 AND url=$2
               ORDER BY generated_at DESC LIMIT 1""",
            client_id, url,
        )
    return dict(row) if row else None


async def get_applied_fix_paths(client_id: str, url: str) -> list[str]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT fix_path FROM fix_history
               WHERE client_id=$1 AND url=$2 AND status IN ('pushed', 'verified')
               ORDER BY generated_at""",
            client_id, url,
        )
    return [r["fix_path"] for r in rows if r["fix_path"]]


# ── Design history (Neon) ─────────────────────────────────────────────────────

async def save_design(
    client_id: str,
    source: str,
    mode: str,
    dir_path: str,
) -> int:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO design_history (client_id, source, mode, dir_path)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            client_id, source, mode, dir_path,
        )
    logger.info("[db] Design збережено: %s mode=%s", source[:80], mode)
    return row["id"]


async def get_last_design(client_id: str, source: str) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM design_history
               WHERE client_id=$1 AND source=$2
               ORDER BY generated_at DESC LIMIT 1""",
            client_id, source,
        )
    return dict(row) if row else None


# ── Analysis history ──────────────────────────────────────────────────────────

async def get_recent_analyses(client_id: str, limit: int = 10) -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, kind, confidence, source_tg_file_id, source_tg_msg_id, created_at
               FROM analysis_history WHERE client_id=$1 ORDER BY created_at DESC LIMIT $2""",
            client_id, limit,
        )
    return [dict(r) for r in rows]
