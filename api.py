import html
import os
import secrets
import sqlite3

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import (
    FastAPI,
    HTTPException,
)

from pydantic import BaseModel

from telegram import Bot


# ============================================================================
# CONFIG
# ============================================================================

BOT_TOKEN = os.getenv(
    "BOT_TOKEN"
)

DB_PATH = os.getenv(
    "DB_PATH",
    "queue_bot.db",
)

TIMEZONE = os.getenv(
    "TIMEZONE",
    "Asia/Tashkent",
)

WEB_CHAT_ID = int(
    os.getenv(
        "WEB_CHAT_ID",
        "0",
    )
)

THREAD_ID_RAW = os.getenv(
    "ALLOWED_THREAD_ID",
    "",
).strip()

ALLOWED_THREAD_ID = (
    int(THREAD_ID_RAW)
    if THREAD_ID_RAW
    else None
)

TZ = ZoneInfo(
    TIMEZONE
)

SLOT_MINUTES = int(
    os.getenv(
        "SLOT_MINUTES",
        "60",
    )
)


if not BOT_TOKEN:

    raise RuntimeError(
        "BOT_TOKEN не задан"
    )


app = FastAPI(
    title="Queue API"
)

bot = Bot(
    BOT_TOKEN
)


# ============================================================================
# DATABASE
# ============================================================================

_conn = None


def get_conn():

    global _conn

    if _conn is None:

        _conn = sqlite3.connect(
            DB_PATH,
            check_same_thread=False,
        )

        _conn.row_factory = sqlite3.Row

        _conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        _conn.execute(
            "PRAGMA busy_timeout=5000"
        )

    return _conn


def init_db():

    conn = get_conn()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS queue_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            chat_id INTEGER NOT NULL,

            user_id INTEGER,

            display_name TEXT NOT NULL,

            status TEXT NOT NULL,

            joined_at TEXT NOT NULL,

            confirm_deadline TEXT,

            started_at TEXT,

            end_at TEXT,

            finished_at TEXT,

            source TEXT NOT NULL
                DEFAULT 'telegram',

            web_token TEXT
        )
        """
    )

    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(queue_entries)"
        ).fetchall()
    }

    if "source" not in columns:

        conn.execute(
            """
            ALTER TABLE queue_entries
            ADD COLUMN source
            TEXT NOT NULL
            DEFAULT 'telegram'
            """
        )

    if "web_token" not in columns:

        conn.execute(
            """
            ALTER TABLE queue_entries
            ADD COLUMN web_token TEXT
            """
        )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_queue_web_token

        ON queue_entries(
            web_token
        )
        """
    )

    conn.commit()


init_db()


# ============================================================================
# TELEGRAM
# ============================================================================

async def telegram_message(
    chat_id,
    text,
):

    kwargs = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    if ALLOWED_THREAD_ID is not None:

        kwargs[
            "message_thread_id"
        ] = ALLOWED_THREAD_ID

    await bot.send_message(
        **kwargs
    )


# ============================================================================
# HELPERS
# ============================================================================

def now():

    return datetime.now(
        TZ
    )


def get_web_entry(
    entry_id,
    token,
):

    conn = get_conn()

    return conn.execute(
        """
        SELECT *
        FROM queue_entries

        WHERE id = ?

        AND web_token = ?

        AND source = 'web'

        LIMIT 1
        """,
        (
            entry_id,
            token,
        ),
    ).fetchone()


def set_status(
    entry_id,
    status,
    **fields,
):

    values = dict(fields)

    values["status"] = status

    columns = ", ".join(
        f"{key} = ?"
        for key in values
    )

    params = list(
        values.values()
    )

    params.append(
        entry_id
    )

    conn = get_conn()

    conn.execute(
        f"""
        UPDATE queue_entries

        SET {columns}

        WHERE id = ?
        """,
        params,
    )

    conn.commit()


# ============================================================================
# REQUEST MODELS
# ============================================================================

class RegisterRequest(
    BaseModel
):

    nickname: str


class ActionRequest(
    BaseModel
):

    token: str


# ============================================================================
# HEALTH
# ============================================================================

@app.get(
    "/api/health"
)
async def health():

    return {
        "ok": True
    }


# ============================================================================
# REGISTER
# ============================================================================

@app.post(
    "/api/queue/register"
)
async def register(
    data: RegisterRequest,
):

    nickname = (
        data.nickname
        .strip()
    )

    if not nickname:

        raise HTTPException(
            400,
            "Ник пустой",
        )

    if len(nickname) > 64:

        raise HTTPException(
            400,
            "Ник слишком длинный",
        )

    if not WEB_CHAT_ID:

        raise HTTPException(
            500,
            "WEB_CHAT_ID не настроен",
        )

    token = secrets.token_urlsafe(
        32
    )

    conn = get_conn()

    cur = conn.execute(
        """
        INSERT INTO queue_entries (
            chat_id,
            user_id,
            display_name,
            status,
            joined_at,
            source,
            web_token
        )

        VALUES (
            ?,
            NULL,
            ?,
            'waiting',
            ?,
            'web',
            ?
        )
        """,
        (
            WEB_CHAT_ID,
            nickname,
            now().isoformat(),
            token,
        ),
    )

    conn.commit()

    entry_id = cur.lastrowid

    await telegram_message(
        WEB_CHAT_ID,
        (
            f"➕ <b>"
            f"{html.escape(nickname)}"
            f"</b> встал в очередь "
            f"<b>через вебку</b>."
        ),
    )

    return {
        "ok": True,
        "entry_id": entry_id,
        "token": token,
        "nickname": nickname,
        "status": "waiting",
    }


# ============================================================================
# QUEUE
# ============================================================================

@app.get(
    "/api/queue"
)
async def queue():

    if not WEB_CHAT_ID:

        raise HTTPException(
            500,
            "WEB_CHAT_ID не настроен",
        )

    conn = get_conn()

    rows = conn.execute(
        """
        SELECT
            id,
            display_name,
            status,
            source,
            joined_at,
            confirm_deadline,
            started_at,
            end_at

        FROM queue_entries

        WHERE chat_id = ?

        AND status IN (
            'waiting',
            'confirming',
            'active'
        )

        ORDER BY
            CASE
                WHEN status = 'active'
                    THEN 0
                WHEN status = 'confirming'
                    THEN 0
                ELSE 1
            END,

            joined_at
        """,
        (WEB_CHAT_ID,),
    ).fetchall()

    result = []

    for index, row in enumerate(
        rows,
        1,
    ):

        result.append(
            {
                "id": row["id"],
                "nickname": row[
                    "display_name"
                ],
                "status": row[
                    "status"
                ],
                "source": row[
                    "source"
                ],
                "position": index,
                "joined_at": row[
                    "joined_at"
                ],
                "confirm_deadline":
                    row[
                        "confirm_deadline"
                    ],
                "started_at":
                    row[
                        "started_at"
                    ],
                "end_at":
                    row[
                        "end_at"
                    ],
            }
        )

    return {
        "ok": True,
        "queue": result,
    }


# ============================================================================
# MY ENTRY
# ============================================================================

@app.get(
    "/api/queue/{entry_id}"
)
async def my_entry(
    entry_id: int,
    token: str,
):

    entry = get_web_entry(
        entry_id,
        token,
    )

    if not entry:

        raise HTTPException(
            403,
            "Это не твоя очередь",
        )

    return {
        "ok": True,
        "entry": {
            "id": entry["id"],
            "nickname":
                entry["display_name"],
            "status":
                entry["status"],
            "source":
                entry["source"],
            "joined_at":
                entry["joined_at"],
            "confirm_deadline":
                entry["confirm_deadline"],
            "started_at":
                entry["started_at"],
            "end_at":
                entry["end_at"],
        },
    }


# ============================================================================
# CONFIRM
# ============================================================================

@app.post(
    "/api/queue/{entry_id}/confirm"
)
async def confirm(
    entry_id: int,
    data: ActionRequest,
):

    entry = get_web_entry(
        entry_id,
        data.token,
    )

    if not entry:

        raise HTTPException(
            403,
            "Это не твоя очередь",
        )

    if entry["status"] != "confirming":

        raise HTTPException(
            400,
            "Сейчас подтверждение невозможно",
        )

    start = now()

    end = (
        start
        +
        __import__(
            "datetime"
        ).timedelta(
            minutes=SLOT_MINUTES
        )
    )

    # Атомарно.
    #
    # Если бот одновременно успел
    # истечь подтверждением,
    # UPDATE просто не изменит строку.
    conn = get_conn()

    cur = conn.execute(
        """
        UPDATE queue_entries

        SET
            status = 'active',
            started_at = ?,
            end_at = ?,
            confirm_deadline = NULL

        WHERE id = ?

        AND web_token = ?

        AND source = 'web'

        AND status = 'confirming'
        """,
        (
            start.isoformat(),
            end.isoformat(),
            entry_id,
            data.token,
        ),
    )

    conn.commit()

    if cur.rowcount != 1:

        raise HTTPException(
            409,
            "Очередь уже изменилась. Обнови страницу.",
        )

    await telegram_message(
        entry["chat_id"],
        (
            f"🟢 <b>"
            f"{html.escape(entry['display_name'])}"
            f"</b> подтвердил очередь "
            f"<b>через вебку</b>.\n\n"
            f"Начало: {start:%H:%M}\n"
            f"Конец: {end:%H:%M}"
        ),
    )

    return {
        "ok": True,
        "status": "active",
        "started_at":
            start.isoformat(),
        "end_at":
            end.isoformat(),
    }


# ============================================================================
# CANCEL
# ============================================================================

@app.post(
    "/api/queue/{entry_id}/cancel"
)
async def cancel(
    entry_id: int,
    data: ActionRequest,
):

    entry = get_web_entry(
        entry_id,
        data.token,
    )

    if not entry:

        raise HTTPException(
            403,
            "Это не твоя очередь",
        )

    if entry["status"] not in (
        "waiting",
        "confirming",
        "active",
    ):

        raise HTTPException(
            400,
            "Эту очередь уже нельзя отменить",
        )

    conn = get_conn()

    cur = conn.execute(
        """
        UPDATE queue_entries

        SET status = 'cancelled'

        WHERE id = ?

        AND web_token = ?

        AND source = 'web'

        AND status IN (
            'waiting',
            'confirming',
            'active'
        )
        """,
        (
            entry_id,
            data.token,
        ),
    )

    conn.commit()

    if cur.rowcount != 1:

        raise HTTPException(
            409,
            "Очередь уже изменилась",
        )

    await telegram_message(
        entry["chat_id"],
        (
            f"<b>"
            f"{html.escape(entry['display_name'])}"
            f"</b> отменил свою очередь "
            f"<b>через вебку</b>."
        ),
    )

    return {
        "ok": True,
        "status": "cancelled",
    }