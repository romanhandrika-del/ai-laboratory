"""
Database layer — asyncpg + Neon PostgreSQL.
Центральний інтерфейс для всіх агентів.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_neon_pool: asyncpg.Pool | None = None


def _get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db.init() не було викликано")
    return _pool


def _get_neon_pool() -> asyncpg.Pool:
    """Повертає пул до Neon (діалоги). Fallback до основного пулу."""
    return _neon_pool if _neon_pool is not None else _get_pool()


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
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS summary_updated_at TIMESTAMPTZ;
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS summary_msg_count INT DEFAULT 0;
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS client_name TEXT;
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS phone_first_seen TIMESTAMPTZ;

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
ALTER TABLE trainer_suggestions ADD COLUMN IF NOT EXISTS category            TEXT;
ALTER TABLE trainer_suggestions ADD COLUMN IF NOT EXISTS root_cause          TEXT;
ALTER TABLE trainer_suggestions ADD COLUMN IF NOT EXISTS improvement_hypothesis TEXT;
ALTER TABLE trainer_suggestions ADD COLUMN IF NOT EXISTS evidence_quote      TEXT;

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

CREATE TABLE IF NOT EXISTS prompt_versions (
    id          SERIAL PRIMARY KEY,
    client_id   VARCHAR(50) NOT NULL,
    prompt_text TEXT        NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS agent_id    TEXT;
ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS version_num INT;
ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS applied_by  TEXT DEFAULT 'system';
DO $$ BEGIN ALTER TABLE prompt_versions ALTER COLUMN agent_type DROP NOT NULL; EXCEPTION WHEN undefined_column THEN NULL; END; $$;
DO $$ BEGIN ALTER TABLE prompt_versions ALTER COLUMN version_int  DROP NOT NULL; EXCEPTION WHEN undefined_column THEN NULL; END; $$;
CREATE INDEX IF NOT EXISTS idx_prompt_versions_ca
    ON prompt_versions(client_id, agent_id, version_num DESC);

CREATE TABLE IF NOT EXISTS prompts (
    id                 SERIAL PRIMARY KEY,
    client_id          VARCHAR(50) NOT NULL,
    current_version_id INT,
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE prompts ADD COLUMN IF NOT EXISTS agent_id          TEXT;
ALTER TABLE prompts ADD COLUMN IF NOT EXISTS prompt_text       TEXT;
ALTER TABLE prompts ADD COLUMN IF NOT EXISTS current_version_id INT;
ALTER TABLE prompts ADD COLUMN IF NOT EXISTS updated_at        TIMESTAMPTZ DEFAULT NOW();
DO $$ BEGIN ALTER TABLE prompts ALTER COLUMN agent_type DROP NOT NULL; EXCEPTION WHEN undefined_column THEN NULL; END; $$;

CREATE TABLE IF NOT EXISTS pending_reviews (
    id         SERIAL PRIMARY KEY,
    client_id  VARCHAR(50) NOT NULL,
    new_text   TEXT        NOT NULL,
    status     VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS agent_id            TEXT DEFAULT 'sales_instagram';
DO $$ BEGIN ALTER TABLE pending_reviews ALTER COLUMN agent_type  DROP NOT NULL; EXCEPTION WHEN undefined_column THEN NULL; END; $$;
DO $$ BEGIN ALTER TABLE pending_reviews ALTER COLUMN section_id  DROP NOT NULL; EXCEPTION WHEN undefined_column THEN NULL; END; $$;
DO $$ BEGIN ALTER TABLE pending_reviews ALTER COLUMN old_text    DROP NOT NULL; EXCEPTION WHEN undefined_column THEN NULL; END; $$;
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS section_id          VARCHAR(100);
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS old_text            TEXT;
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS reason              TEXT;
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS based_on_version_id INT;
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS reject_category     VARCHAR(20);
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS reviewed_at         TIMESTAMPTZ;
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS reviewed_by         TEXT;
CREATE INDEX IF NOT EXISTS idx_pending_reviews_cs
    ON pending_reviews(client_id, status);
"""


async def init() -> None:
    global _pool, _neon_pool
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
    neon_url = os.getenv("NEON_DATABASE_URL")
    if neon_url:
        _neon_pool = await asyncpg.create_pool(
            neon_url,
            min_size=1,
            max_size=2,
            init=_setup_conn,
        )
        logger.info("[db] Neon пул ініціалізовано (діалоги)")
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
            await conn.execute(
                """INSERT INTO dialogs (client_id, user_id, source, messages)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (client_id, user_id, source) DO UPDATE SET
                       messages   = $4,
                       updated_at = NOW()""",
                client_id, user_id, source, messages,
            )


async def upsert_dialog_messages(
    client_id: str,
    user_id: str,
    source: str,
    messages: list[dict[str, Any]],
    client_name: str | None = None,
) -> None:
    """Історичний імпорт готового діалогу зі збереженими timestamps."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO dialogs (client_id, user_id, source, messages, client_name, updated_at)
               VALUES ($1, $2, $3, $4, $5, NOW())
               ON CONFLICT (client_id, user_id, source) DO UPDATE SET
                   messages    = $4,
                   client_name = COALESCE(dialogs.client_name, $5),
                   updated_at  = NOW()""",
            client_id,
            user_id,
            source,
            messages,
            client_name or None,
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


async def get_all_messages(client_id: str, user_id: str, source: str) -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT messages FROM dialogs WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )
    return list(row["messages"]) if row else []


async def get_summary(client_id: str, user_id: str, source: str) -> str | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT summary FROM dialogs WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )
    return row["summary"] if row else None


async def save_summary(
    client_id: str,
    user_id: str,
    source: str,
    summary: str,
    msg_count: int,
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE dialogs
               SET summary=$4, summary_updated_at=NOW(), summary_msg_count=$5
               WHERE client_id=$1 AND user_id=$2 AND source=$3""",
            client_id, user_id, source, summary, msg_count,
        )


async def get_summary_msg_count(client_id: str, user_id: str, source: str) -> tuple[int, int]:
    """Повертає (total_messages, summary_msg_count) для рядка dialogs."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT jsonb_array_length(messages) AS total, COALESCE(summary_msg_count, 0) AS smc "
            "FROM dialogs WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )
    if row is None:
        return 0, 0
    return row["total"], row["smc"]


# ── Client profile ───────────────────────────────────────────────────────────

async def update_client_profile(
    client_id: str,
    user_id: str,
    source: str,
    name: str | None = None,
    phone: str | None = None,
) -> None:
    """Заповнює client_name і phone тільки якщо вони ще порожні."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE dialogs
               SET
                 client_name      = COALESCE(client_name, $4),
                 phone            = COALESCE(phone, $5),
                 phone_first_seen = CASE
                   WHEN phone IS NULL AND $5 IS NOT NULL THEN NOW()
                   ELSE phone_first_seen
                 END
               WHERE client_id=$1 AND user_id=$2 AND source=$3""",
            client_id, user_id, source, name or None, phone or None,
        )


async def get_client_profile(
    client_id: str,
    user_id: str,
    source: str,
) -> dict:
    """Повертає {client_name, phone, phone_first_seen} або порожній dict."""
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT client_name, phone, phone_first_seen FROM dialogs "
            "WHERE client_id=$1 AND user_id=$2 AND source=$3",
            client_id, user_id, source,
        )
    if not row:
        return {}
    return {
        "client_name": row["client_name"],
        "phone": row["phone"],
        "phone_first_seen": row["phone_first_seen"],
    }


# ── Review / Stats ────────────────────────────────────────────────────────────

async def get_dialogs_review(
    client_id: str,
    limit: int = 30,
    only_low: bool = False,
    source: str = "instagram",
    days_back: int | None = None,
) -> list[dict]:
    """Пари user/assistant з meta для Trainer і /review."""
    pool = _get_neon_pool()
    async with pool.acquire() as conn:
        if days_back is not None:
            rows = await conn.fetch(
                "SELECT messages FROM dialogs WHERE client_id=$1 AND source=$2"
                " AND updated_at >= NOW() - ($3 || ' days')::interval ORDER BY updated_at DESC",
                client_id, source, str(days_back),
            )
        else:
            rows = await conn.fetch(
                "SELECT messages FROM dialogs WHERE client_id=$1 AND source=$2 ORDER BY updated_at DESC",
                client_id,
                source,
            )
    pairs: list[dict] = []
    for row in rows:
        msgs = list(row["messages"])
        for i in range(0, len(msgs) - 1):
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
                "by": meta.get("by", "bot"),
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
    category: str = "",
    root_cause: str = "",
    improvement_hypothesis: str = "",
    evidence_quote: str = "",
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO trainer_suggestions
               (client_id, type, priority, problem, suggestion,
                category, root_cause, improvement_hypothesis, evidence_quote)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            client_id, type, priority, problem, suggestion,
            category, root_cause, improvement_hypothesis, evidence_quote,
        )


async def mark_trainer_suggestion(suggestion_id: int, status: str) -> bool:
    pool = _get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE trainer_suggestions SET status=$1 WHERE id=$2",
            status, suggestion_id,
        )
    return result == "UPDATE 1"


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


# ── Prompt versioning (Sales Trainer) ─────────────────────────────────────────

_prompt_cache: dict[str, tuple[str, float]] = {}
_PROMPT_TTL = 60.0


async def get_current_prompt(client_id: str, agent_id: str) -> str | None:
    """Повертає актуальний промпт з in-memory кешем TTL=60s."""
    key = f"{client_id}:{agent_id}"
    now = time.time()
    if key in _prompt_cache and _prompt_cache[key][1] > now:
        return _prompt_cache[key][0]
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT prompt_text FROM prompts WHERE client_id=$1 AND agent_id=$2",
            client_id, agent_id,
        )
    if row is None:
        return None
    text = row["prompt_text"]
    _prompt_cache[key] = (text, now + _PROMPT_TTL)
    return text


async def get_prompt_current_version_id(client_id: str, agent_id: str) -> int | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_version_id FROM prompts WHERE client_id=$1 AND agent_id=$2",
            client_id, agent_id,
        )
    return row["current_version_id"] if row else None


async def get_prompt_version_text(version_id: int) -> str | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT prompt_text FROM prompt_versions WHERE id=$1",
            version_id,
        )
    return row["prompt_text"] if row else None


async def apply_prompt_patch_multi(patches: list[dict]) -> list[int]:
    """Атомарно патчить кілька (client_id, agent_id). Повертає список нових version_id."""
    pool = _get_pool()
    version_ids: list[int] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for p in patches:
                cid = p["client_id"]
                aid = p["agent_id"]
                new_text = p["new_text"]
                applied_by = p.get("applied_by", "system")
                row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(version_num), 0) AS max_v "
                    "FROM prompt_versions WHERE client_id=$1 AND agent_id=$2",
                    cid, aid,
                )
                new_ver = row["max_v"] + 1
                v_row = await conn.fetchrow(
                    """INSERT INTO prompt_versions
                         (client_id, agent_id, version_num, prompt_text, applied_by)
                       VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                    cid, aid, new_ver, new_text, applied_by,
                )
                vid = v_row["id"]
                version_ids.append(vid)
                updated = await conn.fetchval(
                    """UPDATE prompts SET prompt_text=$3, current_version_id=$4, updated_at=NOW()
                       WHERE client_id=$1 AND agent_id=$2 RETURNING id""",
                    cid, aid, new_text, vid,
                )
                if not updated:
                    await conn.execute(
                        """INSERT INTO prompts (client_id, agent_id, prompt_text, current_version_id)
                           VALUES ($1,$2,$3,$4)""",
                        cid, aid, new_text, vid,
                    )
                _prompt_cache.pop(f"{cid}:{aid}", None)
    return version_ids


async def save_trainer_review(
    client_id: str,
    agent_id: str,
    section_id: str,
    old_text: str,
    new_text: str,
    reason: str,
    based_on_version_id: int | None,
) -> int | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            """SELECT id FROM pending_reviews
               WHERE client_id=$1 AND agent_id=$2 AND section_id=$3 AND new_text=$4 AND status='pending'""",
            client_id, agent_id, section_id, new_text,
        )
        if existing:
            return None
        row = await conn.fetchrow(
            """INSERT INTO pending_reviews
                 (client_id, agent_id, section_id, old_text, new_text, reason, based_on_version_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            client_id, agent_id, section_id, old_text, new_text, reason, based_on_version_id,
        )
    return row["id"]


async def list_trainer_reviews(client_id: str, status: str = "pending") -> list[dict]:
    pool = _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM pending_reviews WHERE client_id=$1 AND status=$2 ORDER BY created_at DESC",
            client_id, status,
        )
    return [dict(r) for r in rows]


async def get_trainer_review(review_id: int) -> dict | None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pending_reviews WHERE id=$1",
            review_id,
        )
    return dict(row) if row else None


async def update_trainer_review_status(
    review_id: int,
    status: str,
    reject_category: str | None = None,
    reviewed_by: str = "manager",
) -> None:
    pool = _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE pending_reviews
               SET status=$2,
                   reject_category = COALESCE($3, reject_category),
                   reviewed_at     = NOW(),
                   reviewed_by     = $4
               WHERE id=$1""",
            review_id, status, reject_category, reviewed_by,
        )
