"""Логика уведомлений: системные уведомления macOS, popup-окна и планировщик."""

import subprocess
import tkinter as tk
import traceback
from datetime import datetime, timedelta
from tkinter import ttk
from typing import Callable

from db import STATUS_CANCELLED, STATUS_DONE, Reminder, ReminderDB

CHECK_INTERVAL_MS = 5_000                 # как часто проверять базу
OVERDUE_GRACE = timedelta(minutes=5)      # сколько ждать реакции, прежде чем «Просрочено»
SNOOZE_DELTA = timedelta(minutes=10)      # «Отложить»


def send_system_notification(title: str, message: str) -> None:
    """Показать уведомление в Центре уведомлений macOS через osascript.

    Текст передаётся через argv, чтобы не экранировать кавычки внутри AppleScript.
    Вызов неблокирующий.
    """
    script = [
        "osascript",
        "-e", "on run argv",
        "-e", 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
        "-e", "end run",
        title, message or " ",
    ]
    try:
        subprocess.Popen(script, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        traceback.print_exc()


def disable_app_nap() -> None:
    """Не дать macOS «усыпить» процесс, когда окно свёрнуто (иначе таймеры могут опаздывать).

    Требует pyobjc (pip install pyobjc-framework-Cocoa). Без него просто ничего не делает.
    """
    try:
        from Foundation import NSActivityUserInitiatedAllowingIdleSystemSleep, NSProcessInfo
    except ImportError:
        return
    global _app_nap_activity
    _app_nap_activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
        NSActivityUserInitiatedAllowingIdleSystemSleep, "Ожидание напоминаний"
    )


_app_nap_activity = None


class ReminderPopup(tk.Toplevel):
    """Окно напоминания поверх всех окон."""

    def __init__(self, master: tk.Misc, reminder: Reminder,
                 on_action: Callable[[int, str], None]):
        super().__init__(master)
        self.reminder_id = reminder.id
        self._on_action = on_action

        self.title("⏰ Напоминание")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", lambda: self._act("dismiss"))

        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=reminder.title, font=("Helvetica", 18, "bold"),
                  wraplength=380).pack(anchor="w")
        when = reminder.due_at.strftime("%d.%m.%Y %H:%M")
        if reminder.is_recurring:
            when += f"  ·  повтор: {reminder.repeat_label}"
        ttk.Label(body, text=when, foreground="gray").pack(anchor="w", pady=(2, 10))
        if reminder.description:
            ttk.Label(body, text=reminder.description, wraplength=380,
                      justify="left").pack(anchor="w", pady=(0, 12))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Готово",
                   command=lambda: self._act("done")).pack(side="left")
        minutes = int(SNOOZE_DELTA.total_seconds() // 60)
        ttk.Button(buttons, text=f"Отложить на {minutes} мин",
                   command=lambda: self._act("snooze")).pack(side="left", padx=6)
        ttk.Button(buttons, text="Отменить",
                   command=lambda: self._act("cancel")).pack(side="left")
        ttk.Button(buttons, text="Закрыть",
                   command=lambda: self._act("dismiss")).pack(side="right")

        self._center()
        self.lift()
        self.focus_force()
        self.bell()
        # На macOS topmost иногда не применяется до первой отрисовки — повторяем
        self.after(300, lambda: (self.attributes("-topmost", True), self.lift()))

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"+{x}+{y}")

    def _act(self, action: str) -> None:
        self._on_action(self.reminder_id, action)


class ReminderScheduler:
    """Периодически проверяет базу в главном цикле tkinter.

    Цикл tkinter продолжает работать, когда окно свёрнуто, поэтому
    уведомления приходят и в этом случае.
    """

    def __init__(self, root: tk.Tk, db: ReminderDB,
                 on_change: Callable[[], None] | None = None):
        self.root = root
        self.db = db
        self.on_change = on_change
        self._popups: dict[int, ReminderPopup] = {}

    def start(self) -> None:
        self._tick()

    def _tick(self) -> None:
        try:
            self.check_now()
        except Exception:
            traceback.print_exc()
        finally:
            self.root.after(CHECK_INTERVAL_MS, self._tick)

    def check_now(self) -> None:
        now = datetime.now()
        changed = False

        for reminder in self.db.get_due_for_notification(now):
            self.db.mark_notified(reminder.id)
            self.db.spawn_next(reminder.id, now)
            self._notify(reminder)
            changed = True

        if self.db.mark_overdue(now - OVERDUE_GRACE):
            changed = True

        if changed:
            self._changed()

    def _notify(self, reminder: Reminder) -> None:
        send_system_notification(reminder.title, reminder.description)
        if reminder.id not in self._popups:
            self._popups[reminder.id] = ReminderPopup(self.root, reminder, self._handle_action)

    def _handle_action(self, reminder_id: int, action: str) -> None:
        if action == "done":
            self.db.set_status(reminder_id, STATUS_DONE)
        elif action == "cancel":
            self.db.set_status(reminder_id, STATUS_CANCELLED)
        elif action == "snooze":
            self.db.snooze(reminder_id, datetime.now() + SNOOZE_DELTA)
        self.close_popup(reminder_id)
        self._changed()

    def close_popup(self, reminder_id: int) -> None:
        popup = self._popups.pop(reminder_id, None)
        if popup is not None:
            popup.destroy()

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()
