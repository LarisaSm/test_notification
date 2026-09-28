"""Слой хранения напоминаний в SQLite3."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_OVERDUE = "overdue"
STATUS_CANCELLED = "cancelled"

STATUS_LABELS = {
    STATUS_PENDING: "Ожидает",
    STATUS_DONE: "Готово",
    STATUS_OVERDUE: "Просрочено",
    STATUS_CANCELLED: "Отменено",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    due_at      TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'overdue', 'cancelled')),
    notified    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders (status, due_at);
"""


def _fmt(dt: datetime) -> str:
    return dt.strftime(DATETIME_FMT)


def _parse(value: str) -> datetime:
    return datetime.strptime(value, DATETIME_FMT)


@dataclass
class Reminder:
    id: int
    title: str
    description: str
    due_at: datetime
    status: str
    notified: bool
    created_at: datetime

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Reminder":
        return cls(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            due_at=_parse(row["due_at"]),
            status=row["status"],
            notified=bool(row["notified"]),
            created_at=_parse(row["created_at"]),
        )


class ReminderDB:
    """Все операции с таблицей напоминаний.

    Соединение используется только из главного потока tkinter,
    поэтому дополнительная синхронизация не нужна.
    """

    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        # CREATE ... IF NOT EXISTS: при каждом старте таблицы создаются, если их нет
        with self.conn:
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- CRUD ---------------------------------------------------------------

    def add(self, title: str, description: str, due_at: datetime) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO reminders (title, description, due_at, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, description, _fmt(due_at), STATUS_PENDING, _fmt(datetime.now())),
            )
        return cur.lastrowid

    def get(self, reminder_id: int) -> Reminder | None:
        row = self.conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        return Reminder.from_row(row) if row else None

    def get_all(self, status: str | None = None) -> list[Reminder]:
        if status is None:
            rows = self.conn.execute("SELECT * FROM reminders ORDER BY due_at")
        else:
            rows = self.conn.execute(
                "SELECT * FROM reminders WHERE status = ? ORDER BY due_at", (status,)
            )
        return [Reminder.from_row(r) for r in rows]

    def delete(self, reminder_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    def set_status(self, reminder_id: int, status: str) -> None:
        if status not in STATUS_LABELS:
            raise ValueError(f"Неизвестный статус: {status}")
        with self.conn:
            self.conn.execute(
                "UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id)
            )

    def snooze(self, reminder_id: int, new_due_at: datetime) -> None:
        """Перенести срабатывание: напоминание снова ждёт и будет показано ещё раз."""
        with self.conn:
            self.conn.execute(
                "UPDATE reminders SET due_at = ?, status = ?, notified = 0 WHERE id = ?",
                (_fmt(new_due_at), STATUS_PENDING, reminder_id),
            )

    # --- Для планировщика ---------------------------------------------------

    def get_due_for_notification(self, now: datetime) -> list[Reminder]:
        """Ожидающие напоминания, время которых наступило, но уведомления ещё не было."""
        rows = self.conn.execute(
            "SELECT * FROM reminders "
            "WHERE status = ? AND notified = 0 AND due_at <= ? ORDER BY due_at",
            (STATUS_PENDING, _fmt(now)),
        )
        return [Reminder.from_row(r) for r in rows]

    def mark_notified(self, reminder_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE reminders SET notified = 1 WHERE id = ?", (reminder_id,)
            )

    def mark_overdue(self, deadline: datetime) -> int:
        """Перевести в «Просрочено» все ожидающие со временем раньше deadline."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE reminders SET status = ? WHERE status = ? AND due_at <= ?",
                (STATUS_OVERDUE, STATUS_PENDING, _fmt(deadline)),
            )
        return cur.rowcount
