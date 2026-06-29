"""PostgreSQL data layer for MAP.

Stores users, settings groups, and app config in Postgres (e.g. Neon) so data
survives restarts. The public functions keep the same shapes the rest of the
app already expects:

    load_users()  -> {"users": {username: {...}}}
    save_users(data)
    list_groups() -> [name, ...]
    load_group(name) -> dict
    save_group(name, data)
    delete_group(name)
    load_group_template() -> dict
    save_group_template(data)
"""

import os
import logging
from contextlib import contextmanager
from typing import List, Optional

from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb

log = logging.getLogger("jira_agent.db")

_pool: Optional[ConnectionPool] = None


def init_pool() -> ConnectionPool:
    global _pool
    db_url = os.getenv("APP_DB_URL", "")
    if not db_url:
        raise RuntimeError("APP_DB_URL이 .env에 설정되어 있지 않습니다.")
    if _pool is None:
        _pool = ConnectionPool(
            db_url,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True},
            open=True,
        )
        _pool.wait(timeout=15)
        log.info("PostgreSQL connection pool ready.")
    return _pool


@contextmanager
def get_conn():
    pool = init_pool()
    with pool.connection() as conn:
        yield conn


def init_schema() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
                default_group TEXT NOT NULL DEFAULT 'default'
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings_groups (
                name TEXT PRIMARY KEY,
                data JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """
        )
        # 주간 보고: 사용자별 형식(텍스트 + 이미지 샘플)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_report_config (
                username      TEXT PRIMARY KEY,
                format_text   TEXT  NOT NULL DEFAULT '',
                format_assets JSONB NOT NULL DEFAULT '[]'::jsonb,
                guide_prompt  TEXT  NOT NULL DEFAULT ''
            );
            """
        )
        # 기존 테이블에 guide_prompt 컬럼이 없을 경우 추가 (마이그레이션)
        conn.execute(
            "ALTER TABLE weekly_report_config "
            "ADD COLUMN IF NOT EXISTS guide_prompt TEXT NOT NULL DEFAULT ''"
        )
        # 월간 운영보고: 사용자별 옵션(상태 일괄 종료, 담당자 기본값, 가이드 등)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_report_config (
                username TEXT PRIMARY KEY,
                options  JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            """
        )
    log.info("Schema ensured (users, settings_groups, app_config, "
             "weekly_report_config, monthly_report_config).")


# ---------- users ----------

def load_users() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT username, password_hash, salt, is_admin, default_group FROM users"
        ).fetchall()
    users = {}
    for username, password_hash, salt, is_admin, default_group in rows:
        users[username] = {
            "password_hash": password_hash,
            "salt": salt,
            "is_admin": bool(is_admin),
            "default_group": default_group,
        }
    return {"users": users}


def save_users(data: dict) -> None:
    """Persist the whole users dict (upsert all + delete the ones that vanished)."""
    users = data.get("users", {})
    names = list(users.keys())
    with get_conn() as conn:
        with conn.transaction():
            if names:
                conn.execute(
                    "DELETE FROM users WHERE username <> ALL(%s)", (names,)
                )
            else:
                conn.execute("DELETE FROM users")
            for username, info in users.items():
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, salt, is_admin, default_group)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (username) DO UPDATE SET
                        password_hash = EXCLUDED.password_hash,
                        salt          = EXCLUDED.salt,
                        is_admin      = EXCLUDED.is_admin,
                        default_group = EXCLUDED.default_group
                    """,
                    (
                        username,
                        info["password_hash"],
                        info["salt"],
                        bool(info.get("is_admin", False)),
                        info.get("default_group", "default"),
                    ),
                )


# ---------- settings groups ----------

def list_groups() -> List[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM settings_groups ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def load_group(name: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM settings_groups WHERE name = %s", (name,)
        ).fetchone()
    return row[0] if row else {}


def save_group(name: str, data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings_groups (name, data) VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET data = EXCLUDED.data
            """,
            (name, Jsonb(data)),
        )


def delete_group(name: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM settings_groups WHERE name = %s", (name,))


def group_exists(name: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM settings_groups WHERE name = %s", (name,)
        ).fetchone()
    return row is not None


# ---------- app config (group template, etc.) ----------

def load_group_template() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_config WHERE key = 'group_template'"
        ).fetchone()
    return row[0] if row else {}


def save_group_template(data: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO app_config (key, value) VALUES ('group_template', %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (Jsonb(data),),
        )


# ---------- weekly report (per-user format) ----------

def load_weekly_config(username: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT format_text, format_assets, guide_prompt "
            "FROM weekly_report_config WHERE username = %s",
            (username,),
        ).fetchone()
    if not row:
        return {"format_text": "", "format_assets": [], "guide_prompt": ""}
    return {
        "format_text": row[0] or "",
        "format_assets": row[1] or [],
        "guide_prompt": row[2] or "",
    }


def save_weekly_config(
    username: str, format_text: str, format_assets: list, guide_prompt: str = ""
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO weekly_report_config
                (username, format_text, format_assets, guide_prompt)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                format_text   = EXCLUDED.format_text,
                format_assets = EXCLUDED.format_assets,
                guide_prompt  = EXCLUDED.guide_prompt
            """,
            (username, format_text or "", Jsonb(format_assets or []), guide_prompt or ""),
        )


# ---------- monthly report (per-user options) ----------

def load_monthly_config(username: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT options FROM monthly_report_config WHERE username = %s",
            (username,),
        ).fetchone()
    if not row or not row[0]:
        return {}
    return row[0]


def save_monthly_config(username: str, options: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO monthly_report_config (username, options)
            VALUES (%s, %s)
            ON CONFLICT (username) DO UPDATE SET options = EXCLUDED.options
            """,
            (username, Jsonb(options or {})),
        )
