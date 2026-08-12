import html
import logging
import os
import sqlite3

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


load_dotenv()


BOT_TOKEN = os.getenv("BOT_TOKEN")

DB_PATH = os.getenv(
    "DB_PATH",
    "queue_bot.db",
)

TIMEZONE = os.getenv(
    "TIMEZONE",
    "Asia/Tashkent",
)

TZ = ZoneInfo(TIMEZONE)

SLOT_MINUTES = int(
    os.getenv(
        "SLOT_MINUTES",
        "60",
    )
)

CONFIRM_MINUTES = int(
    os.getenv(
        "CONFIRM_MINUTES",
        "5",
    )
)

SYNC_SECONDS = int(
    os.getenv(
        "SYNC_SECONDS",
        "5",
    )
)

WEB_URL = os.getenv(
    "WEB_URL",
    "",
).rstrip("/")


_thread = os.getenv(
    "ALLOWED_THREAD_ID",
    "",
).strip()

ALLOWED_THREAD_ID = (
    int(_thread)
    if _thread
    else None
)


WARNING_MINUTES = (
    15,
    10,
    5,
)


logging.basicConfig(
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s: "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(
    "queue_bot"
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
        idx_queue_chat_status
        ON queue_entries(
            chat_id,
            status
        )
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


def get_entry(entry_id):

    conn = get_conn()

    return conn.execute(
        """
        SELECT *
        FROM queue_entries
        WHERE id = ?
        """,
        (entry_id,),
    ).fetchone()


def get_user_entry(
    chat_id,
    user_id,
):

    conn = get_conn()

    return conn.execute(
        """
        SELECT *
        FROM queue_entries

        WHERE chat_id = ?
        AND user_id = ?

        AND source = 'telegram'

        AND status IN (
            'waiting',
            'confirming',
            'active'
        )

        ORDER BY id DESC
        LIMIT 1
        """,
        (
            chat_id,
            user_id,
        ),
    ).fetchone()


def get_active_entry(chat_id):

    conn = get_conn()

    return conn.execute(
        """
        SELECT *
        FROM queue_entries

        WHERE chat_id = ?

        AND status IN (
            'confirming',
            'active'
        )

        ORDER BY joined_at
        LIMIT 1
        """,
        (chat_id,),
    ).fetchone()


def get_waiting(chat_id):

    conn = get_conn()

    return conn.execute(
        """
        SELECT *
        FROM queue_entries

        WHERE chat_id = ?
        AND status = 'waiting'

        ORDER BY joined_at
        """,
        (chat_id,),
    ).fetchall()


def get_queue(chat_id):

    current = get_active_entry(
        chat_id
    )

    waiting = get_waiting(
        chat_id
    )

    result = []

    if current:
        result.append(current)

    result.extend(waiting)

    return result


def set_status(
    entry_id,
    status,
    **fields,
):

    conn = get_conn()

    values = dict(fields)

    values["status"] = status

    columns = ", ".join(
        f"{key} = ?"
        for key in values
    )

    params = list(
        values.values()
    )

    params.append(entry_id)

    conn.execute(
        f"""
        UPDATE queue_entries

        SET {columns}

        WHERE id = ?
        """,
        params,
    )

    conn.commit()


def atomic_activate(
    entry_id,
):

    conn = get_conn()

    start = now()

    end = (
        start
        +
        timedelta(
            minutes=SLOT_MINUTES
        )
    )

    cur = conn.execute(
        """
        UPDATE queue_entries

        SET
            status = 'active',
            started_at = ?,
            end_at = ?,
            confirm_deadline = NULL

        WHERE id = ?

        AND status = 'confirming'
        """,
        (
            start.isoformat(),
            end.isoformat(),
            entry_id,
        ),
    )

    conn.commit()

    if cur.rowcount != 1:
        return None

    return (
        start,
        end,
    )


# ============================================================================
# HELPERS
# ============================================================================

def now():

    return datetime.now(TZ)


def parse_dt(value):

    dt = datetime.fromisoformat(
        value
    )

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=TZ
        )

    return dt.astimezone(TZ)


def mention(
    user_id,
    name,
):

    safe = html.escape(
        name
    )

    if user_id:

        return (
            f'<a href="tg://user?id={user_id}">'
            f'{safe}'
            f'</a>'
        )

    return safe


def position(
    chat_id,
    entry_id,
):

    for index, entry in enumerate(
        get_queue(chat_id),
        1,
    ):

        if entry["id"] == entry_id:
            return index

    return None


# ============================================================================
# TELEGRAM
# ============================================================================

async def send(
    context,
    chat_id,
    text,
    reply_markup=None,
):

    kwargs = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": ParseMode.HTML,
    }

    if reply_markup:
        kwargs[
            "reply_markup"
        ] = reply_markup

    if ALLOWED_THREAD_ID is not None:

        kwargs[
            "message_thread_id"
        ] = ALLOWED_THREAD_ID

    try:

        await context.bot.send_message(
            **kwargs
        )

    except Exception:

        logger.exception(
            "Telegram send error"
        )


def web_button():

    if not WEB_URL:
        return None

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Открыть вебку",
                    url=WEB_URL,
                )
            ]
        ]
    )


# ============================================================================
# JOB NAMES
# ============================================================================

def confirm_job(entry_id):

    return f"confirm:{entry_id}"


def warning_job(
    entry_id,
    minutes,
):

    return (
        f"warning:"
        f"{minutes}:"
        f"{entry_id}"
    )


def complete_job(entry_id):

    return f"complete:{entry_id}"


def cancel_jobs(
    context,
    entry_id,
):

    names = [
        confirm_job(entry_id),
        complete_job(entry_id),
    ]

    names.extend(
        warning_job(
            entry_id,
            minutes,
        )
        for minutes in WARNING_MINUTES
    )

    for name in names:

        for job in (
            context.job_queue
            .get_jobs_by_name(name)
        ):

            job.schedule_removal()


def has_job(
    context,
    name,
):

    return bool(
        context.job_queue
        .get_jobs_by_name(name)
    )


# ============================================================================
# QUEUE LOGIC
# ============================================================================

async def promote_next(
    context,
    chat_id,
):

    if get_active_entry(chat_id):
        return

    waiting = get_waiting(
        chat_id
    )

    if not waiting:
        return

    entry = waiting[0]

    deadline = (
        now()
        +
        timedelta(
            minutes=CONFIRM_MINUTES
        )
    )

    set_status(
        entry["id"],
        "confirming",
        confirm_deadline=(
            deadline.isoformat()
        ),
    )

    user = mention(
        entry["user_id"],
        entry["display_name"],
    )

    if entry["source"] == "web":

        text = (
            f"{user}, теперь твоя очередь.\n\n"
            f"Подтверди присутствие через вебку "
            f"в течение {CONFIRM_MINUTES} мин."
        )

        await send(
            context,
            chat_id,
            text,
            web_button(),
        )

    else:

        text = (
            f"{user}, теперь твоя очередь!\n\n"
            f"Отправь «+» в течение "
            f"{CONFIRM_MINUTES} мин."
        )

        await send(
            context,
            chat_id,
            text,
        )

    context.job_queue.run_once(
        confirm_timeout,
        when=timedelta(
            minutes=CONFIRM_MINUTES
        ),
        data={
            "chat_id": chat_id,
            "entry_id": entry["id"],
        },
        name=confirm_job(
            entry["id"]
        ),
    )


async def activate(
    context,
    entry_id,
    source,
):

    entry = get_entry(
        entry_id
    )

    if not entry:
        return False

    if entry["source"] != source:
        return False

    result = atomic_activate(
        entry_id
    )

    if not result:
        return False

    start, end = result

    cancel_jobs(
        context,
        entry_id,
    )

    user = mention(
        entry["user_id"],
        entry["display_name"],
    )

    if source == "web":

        source_text = (
            "подтвердил очередь через вебку"
        )

    else:

        source_text = (
            "подтвердил очередь"
        )

    await send(
        context,
        entry["chat_id"],
        (
            f"{user} {source_text}.\n\n"
            f"Очередь началась.\n"
            f"Время: "
            f"{start:%H:%M}"
            f"–"
            f"{end:%H:%M}"
        ),
    )

    schedule_slot(
        context,
        entry["chat_id"],
        entry_id,
        end,
    )

    return True


# ============================================================================
# CONFIRM TIMEOUT
# ============================================================================

async def confirm_timeout(
    context,
):

    data = context.job.data

    entry = get_entry(
        data["entry_id"]
    )

    if (
        not entry
        or
        entry["status"] != "confirming"
    ):
        return

    set_status(
        entry["id"],
        "expired",
    )

    user = mention(
        entry["user_id"],
        entry["display_name"],
    )

    await send(
        context,
        data["chat_id"],
        (
            f"{user} не подтвердил "
            f"очередь вовремя.\n"
            f"Переходим к следующему."
        ),
    )

    await promote_next(
        context,
        data["chat_id"],
    )


# ============================================================================
# WARNINGS
# ============================================================================

async def warning(
    context,
):

    data = context.job.data

    entry = get_entry(
        data["entry_id"]
    )

    if (
        not entry
        or
        entry["status"] != "active"
    ):
        return

    user = mention(
        entry["user_id"],
        entry["display_name"],
    )

    minutes = data[
        "minutes"
    ]

    queue = get_queue(
        data["chat_id"]
    )

    next_entry = None

    for item in queue:

        if item["id"] != entry["id"]:

            if item["status"] == "waiting":
                next_entry = item
                break

    if next_entry:

        next_user = mention(
            next_entry["user_id"],
            next_entry["display_name"],
        )

        text = (
            f"{user}, до конца твоей "
            f"очереди осталось {minutes} мин.\n\n"
            f"{next_user}, ты следующий. "
            f"Твоя очередь начнётся примерно "
            f"через {minutes} мин."
        )

    else:

        text = (
            f"{user}, до конца твоей "
            f"очереди осталось {minutes} мин."
        )

    await send(
        context,
        data["chat_id"],
        text,
    )


# ============================================================================
# COMPLETE
# ============================================================================

async def complete(
    context,
):

    data = context.job.data

    entry = get_entry(
        data["entry_id"]
    )

    if (
        not entry
        or
        entry["status"] != "active"
    ):
        return

    set_status(
        entry["id"],
        "completed",
        finished_at=(
            now().isoformat()
        ),
    )

    user = mention(
        entry["user_id"],
        entry["display_name"],
    )

    await send(
        context,
        data["chat_id"],
        (
            f"{user}, твоя очередь "
            f"закончилась."
        ),
    )

    await promote_next(
        context,
        data["chat_id"],
    )


def schedule_slot(
    context,
    chat_id,
    entry_id,
    end,
):

    current = now()

    for minutes in WARNING_MINUTES:

        run_at = (
            end
            -
            timedelta(
                minutes=minutes
            )
        )

        delay = (
            run_at - current
        ).total_seconds()

        if delay <= 0:
            continue

        name = warning_job(
            entry_id,
            minutes,
        )

        if has_job(
            context,
            name,
        ):
            continue

        context.job_queue.run_once(
            warning,
            when=delay,
            data={
                "chat_id": chat_id,
                "entry_id": entry_id,
                "minutes": minutes,
            },
            name=name,
        )

    delay = max(
        (
            end - current
        ).total_seconds(),
        0,
    )

    name = complete_job(
        entry_id
    )

    if not has_job(
        context,
        name,
    ):

        context.job_queue.run_once(
            complete,
            when=delay,
            data={
                "chat_id": chat_id,
                "entry_id": entry_id,
            },
            name=name,
        )


# ============================================================================
# DATABASE SYNCHRONIZATION
# ============================================================================

async def sync_database(
    context,
):

    """
    Главная штука для синхронизации.

    API ничего не планирует.
    API только изменяет SQLite.

    Этот цикл каждые N секунд смотрит,
    что произошло в БД, и приводит JobQueue
    в соответствие.
    """

    try:

        # --------------------------------------------------------------
        # 1. Если есть confirming
        # --------------------------------------------------------------

        conn = get_conn()

        confirming = conn.execute(
            """
            SELECT *
            FROM queue_entries

            WHERE status = 'confirming'
            """
        ).fetchall()

        for entry in confirming:

            name = confirm_job(
                entry["id"]
            )

            if not has_job(
                context,
                name,
            ):

                if not entry[
                    "confirm_deadline"
                ]:
                    continue

                deadline = parse_dt(
                    entry[
                        "confirm_deadline"
                    ]
                )

                delay = (
                    deadline - now()
                ).total_seconds()

                if delay <= 0:

                    await confirm_timeout(
                        type(
                            "JobContext",
                            (),
                            {
                                "job": type(
                                    "Job",
                                    (),
                                    {
                                        "data": {
                                            "chat_id":
                                                entry[
                                                    "chat_id"
                                                ],
                                            "entry_id":
                                                entry[
                                                    "id"
                                                ],
                                        }
                                    },
                                )()
                            },
                        )()
                    )

                else:

                    context.job_queue.run_once(
                        confirm_timeout,
                        when=delay,
                        data={
                            "chat_id":
                                entry[
                                    "chat_id"
                                ],
                            "entry_id":
                                entry[
                                    "id"
                                ],
                        },
                        name=name,
                    )

        # --------------------------------------------------------------
        # 2. Если web подтвердил запись
        # --------------------------------------------------------------

        active = conn.execute(
            """
            SELECT *
            FROM queue_entries

            WHERE status = 'active'
            """
        ).fetchall()

        for entry in active:

            end = parse_dt(
                entry["end_at"]
            )

            if end <= now():

                set_status(
                    entry["id"],
                    "completed",
                    finished_at=(
                        now().isoformat()
                    ),
                )

                continue

            schedule_slot(
                context,
                entry["chat_id"],
                entry["id"],
                end,
            )

        # --------------------------------------------------------------
        # 3. Если web отменил active/confirming
        #
        # Если сейчас никто не активен,
        # запускаем следующего.
        # --------------------------------------------------------------

        chats = conn.execute(
            """
            SELECT DISTINCT chat_id
            FROM queue_entries

            WHERE status IN (
                'waiting',
                'confirming',
                'active'
            )
            """
        ).fetchall()

        for row in chats:

            chat_id = row[
                "chat_id"
            ]

            current = get_active_entry(
                chat_id
            )

            if current:
                continue

            waiting = get_waiting(
                chat_id
            )

            if not waiting:
                continue

            first = waiting[0]

            # Если первый waiting, значит
            # никто сейчас не занимает слот.
            if first["status"] == "waiting":

                await promote_next(
                    context,
                    chat_id,
                )

    except Exception:

        logger.exception(
            "Ошибка синхронизации БД"
        )


# ============================================================================
# TELEGRAM HANDLERS
# ============================================================================

async def join(
    update,
    context,
):

    chat_id = update.effective_chat.id
    user = update.effective_user

    existing = get_user_entry(
        chat_id,
        user.id,
    )

    if existing:

        pos = position(
            chat_id,
            existing["id"],
        )

        await update.message.reply_text(
            (
                f"Ты уже в очереди.\n"
                f"Позиция: {pos}"
            )
        )

        return

    display_name = (
        user.full_name
        or
        user.username
        or
        str(user.id)
    )

    conn = get_conn()

    conn.execute(
        """
        INSERT INTO queue_entries (
            chat_id,
            user_id,
            display_name,
            status,
            joined_at,
            source
        )

        VALUES (
            ?,
            ?,
            ?,
            'waiting',
            ?,
            'telegram'
        )
        """,
        (
            chat_id,
            user.id,
            display_name,
            now().isoformat(),
        ),
    )

    conn.commit()

    entry_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    await update.message.reply_text(
        (
            f"{mention(user.id, display_name)} "
            f"встал в очередь.\n"
            f"Позиция: "
            f"{position(chat_id, entry_id)}"
        ),
        parse_mode=ParseMode.HTML,
    )

    await promote_next(
        context,
        chat_id,
    )


async def leave(
    update,
    context,
):

    chat_id = update.effective_chat.id
    user = update.effective_user

    entry = get_user_entry(
        chat_id,
        user.id,
    )

    if not entry:

        await update.message.reply_text(
            "У тебя нет активной очереди."
        )

        return

    was_current = (
        entry["status"]
        in (
            "confirming",
            "active",
        )
    )

    cancel_jobs(
        context,
        entry["id"],
    )

    set_status(
        entry["id"],
        "cancelled",
    )

    await update.message.reply_text(
        (
            f""
            f"{mention(user.id, entry['display_name'])} "
            f"вышел из очереди."
        ),
        parse_mode=ParseMode.HTML,
    )

    if was_current:

        await promote_next(
            context,
            chat_id,
        )


async def confirm(
    update,
    context,
):

    chat_id = update.effective_chat.id
    user = update.effective_user

    entry = get_user_entry(
        chat_id,
        user.id,
    )

    # Очень важно:
    #
    # get_user_entry() ищет только source=telegram.
    #
    # Поэтому Telegram-пользователь
    # физически не сможет подтвердить
    # web-запись.

    if (
        not entry
        or
        entry["status"] != "confirming"
    ):

        await update.message.reply_text(
            "Сейчас тебе нечего подтверждать."
        )

        return

    await activate(
        context,
        entry["id"],
        "telegram",
    )


async def status(
    update,
    context,
):

    chat_id = update.effective_chat.id

    queue = get_queue(
        chat_id
    )

    if not queue:

        await update.message.reply_text(
            "Очередь пустая."
        )

        return

    lines = [
        "Очередь:"
    ]

    for index, entry in enumerate(
        queue,
        1,
    ):

        user = mention(
            entry["user_id"],
            entry["display_name"],
        )

        if entry["status"] == "active":

            end = parse_dt(
                entry["end_at"]
            )

            minutes = max(
                int(
                    (
                        end - now()
                    ).total_seconds()
                    // 60
                ),
                0,
            )

            state = (
                f"сейчас "
                f"(осталось ~{minutes} мин)"
            )

        elif entry["status"] == "confirming":

            state = "подтверждает"

        else:

            state = "ожидает"

        lines.append(
            f"{index}. {user} — {state}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


async def text_handler(
    update,
    context,
):

    if not update.message:
        return

    text = (
        update.message.text
        or ""
    ).strip()

    lowered = text.lower()

    if lowered == "+очередь":

        await join(
            update,
            context,
        )

    elif lowered == "+удалить":

        await leave(
            update,
            context,
        )

    elif lowered == "+статус":

        await status(
            update,
            context,
        )

    elif text == "+":

        await confirm(
            update,
            context,
        )


async def start(
    update,
    context,
):

    await update.message.reply_text(
        (
            "Бот очереди.\n\n"
            "+очередь — встать\n"
            "+удалить — выйти\n"
            "+статус — очередь\n"
            "+ — подтвердить\n\n"
            f"Слот: {SLOT_MINUTES} мин\n"
            f"Подтверждение: {CONFIRM_MINUTES} мин\n"
            "Предупреждения: 15 / 10 / 5 мин."
        )
    )


async def threadid(
    update,
    context,
):

    msg = update.effective_message

    await msg.reply_text(
        (
            f"chat_id: "
            f"{update.effective_chat.id}\n"
            f"thread_id: "
            f"{msg.message_thread_id}"
        )
    )


# ============================================================================
# THREAD FILTER
# ============================================================================

class ThreadFilter(
    filters.UpdateFilter
):

    def filter(
        self,
        update,
    ):

        if ALLOWED_THREAD_ID is None:
            return True

        msg = (
            update.effective_message
        )

        return (
            bool(msg)
            and
            msg.message_thread_id
            ==
            ALLOWED_THREAD_ID
        )


thread_filter = ThreadFilter()


# ============================================================================
# STARTUP
# ============================================================================

COMMANDS = [
    BotCommand(
        "queue",
        "Встать в очередь",
    ),
    BotCommand(
        "leave",
        "Выйти",
    ),
    BotCommand(
        "status",
        "Очередь",
    ),
    BotCommand(
        "confirm",
        "Подтвердить",
    ),
    BotCommand(
        "start",
        "Помощь",
    ),
    BotCommand(
        "threadid",
        "ID темы",
    ),
]


async def post_init(
    application,
):

    await application.bot.set_my_commands(
        COMMANDS
    )

    # Восстанавливаем таймеры
    # после перезапуска.
    await sync_database(
        type(
            "Context",
            (),
            {
                "job_queue":
                    application.job_queue,
                "bot":
                    application.bot,
            },
        )()
    )

    # Главная синхронизация.
    application.job_queue.run_repeating(
        sync_database,
        interval=SYNC_SECONDS,
        first=SYNC_SECONDS,
        name="database-sync",
    )


def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не задан"
        )

    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "threadid",
            threadid,
        )
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
            filters=thread_filter,
        )
    )

    app.add_handler(
        CommandHandler(
            "queue",
            join,
            filters=thread_filter,
        )
    )

    app.add_handler(
        CommandHandler(
            "leave",
            leave,
            filters=thread_filter,
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status,
            filters=thread_filter,
        )
    )

    app.add_handler(
        CommandHandler(
            "confirm",
            confirm,
            filters=thread_filter,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & thread_filter,
            text_handler,
        )
    )

    logger.info(
        "Bot started"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()