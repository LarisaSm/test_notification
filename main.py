"""Точка входа: python3 main.py"""

import tkinter as tk
from pathlib import Path

from db import ReminderDB
from gui import ReminderApp
from notifier import disable_app_nap

DB_PATH = Path(__file__).with_name("reminders.db")


def main() -> None:
    disable_app_nap()
    db = ReminderDB(DB_PATH)
    root = tk.Tk()
    ReminderApp(root, db)
    try:
        root.mainloop()
    finally:
        db.close()


if __name__ == "__main__":
    main()
