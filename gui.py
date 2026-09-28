"""Главное окно приложения на tkinter."""

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from db import (STATUS_CANCELLED, STATUS_DONE, STATUS_LABELS, STATUS_OVERDUE,
                STATUS_PENDING, ReminderDB)
from notifier import ReminderScheduler

ALL_FILTER = "Все"
DATE_FMT = "%d.%m.%Y"
TIME_FMT = "%H:%M"

ROW_COLORS = {
    STATUS_PENDING: "#1f6feb",
    STATUS_DONE: "#2da44e",
    STATUS_OVERDUE: "#cf222e",
    STATUS_CANCELLED: "#8c959f",
}


class AddReminderDialog(tk.Toplevel):
    """Модальное окно создания напоминания."""

    def __init__(self, master: tk.Misc, on_save):
        super().__init__(master)
        self.on_save = on_save
        self.title("Новое напоминание")
        self.resizable(False, False)
        self.transient(master)

        default_due = (datetime.now() + timedelta(hours=1)).replace(second=0, microsecond=0)
        self.title_var = tk.StringVar()
        self.date_var = tk.StringVar(value=default_due.strftime(DATE_FMT))
        self.time_var = tk.StringVar(value=default_due.strftime(TIME_FMT))

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Заголовок:").grid(row=0, column=0, sticky="w")
        title_entry = ttk.Entry(frm, textvariable=self.title_var, width=40)
        title_entry.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(frm, text="Описание:").grid(row=1, column=0, sticky="nw")
        self.desc_text = tk.Text(frm, width=40, height=5, wrap="word")
        self.desc_text.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(frm, text="Дата (ДД.ММ.ГГГГ):").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.date_var, width=12).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(frm, text="Время (ЧЧ:ММ):").grid(row=2, column=2, sticky="e", padx=(8, 4))
        ttk.Entry(frm, textvariable=self.time_var, width=6).grid(row=2, column=3, sticky="w")

        quick = ttk.Frame(frm)
        quick.grid(row=3, column=1, columnspan=3, sticky="w", pady=(0, 8))
        for label, delta in (("+15 мин", timedelta(minutes=15)),
                             ("+1 час", timedelta(hours=1)),
                             ("+1 день", timedelta(days=1))):
            ttk.Button(quick, text=label,
                       command=lambda d=delta: self._set_from_now(d)).pack(side="left", padx=(0, 4))

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=4, sticky="e")
        ttk.Button(btns, text="Отмена", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="right", padx=6)

        self.bind("<Return>", lambda e: self._save() if e.widget is not self.desc_text else None)
        self.bind("<Escape>", lambda e: self.destroy())
        title_entry.focus_set()
        self.grab_set()

    def _set_from_now(self, delta: timedelta) -> None:
        due = datetime.now() + delta
        self.date_var.set(due.strftime(DATE_FMT))
        self.time_var.set(due.strftime(TIME_FMT))

    def _save(self) -> None:
        title = self.title_var.get().strip()
        description = self.desc_text.get("1.0", "end").strip()
        if not title:
            messagebox.showerror("Ошибка", "Введите заголовок.", parent=self)
            return
        try:
            due_at = datetime.strptime(
                f"{self.date_var.get().strip()} {self.time_var.get().strip()}",
                f"{DATE_FMT} {TIME_FMT}",
            )
        except ValueError:
            messagebox.showerror("Ошибка", "Неверный формат даты или времени.\n"
                                 "Пример: 31.12.2026 и 18:30", parent=self)
            return
        if due_at <= datetime.now():
            messagebox.showerror("Ошибка", "Время срабатывания должно быть в будущем.", parent=self)
            return
        self.on_save(title, description, due_at)
        self.destroy()


class ReminderApp:
    """Главное окно: список напоминаний, фильтр и действия."""

    def __init__(self, root: tk.Tk, db: ReminderDB):
        self.root = root
        self.db = db
        self.scheduler = ReminderScheduler(root, db, on_change=self.refresh)

        root.title("Напоминалка")
        root.geometry("760x520")
        root.minsize(600, 400)
        # Закрытие окна сворачивает его в Dock — уведомления продолжают работать.
        root.protocol("WM_DELETE_WINDOW", root.iconify)
        # Клик по иконке в Dock разворачивает окно, Cmd+Q — полный выход.
        root.createcommand("::tk::mac::ReopenApplication", self._restore)
        root.createcommand("::tk::mac::Quit", self.quit)

        self._build_ui()
        self.refresh()
        self.scheduler.start()

    # --- UI -------------------------------------------------------------------

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        top.pack(fill="x")

        ttk.Label(top, text="Фильтр:").pack(side="left")
        self.filter_var = tk.StringVar(value=ALL_FILTER)
        filter_box = ttk.Combobox(top, textvariable=self.filter_var, state="readonly", width=14,
                                  values=[ALL_FILTER, *STATUS_LABELS.values()])
        filter_box.pack(side="left", padx=(4, 0))
        filter_box.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Button(top, text="＋ Добавить", command=self.add_reminder).pack(side="right")

        table = ttk.Frame(self.root, padding=10)
        table.pack(fill="both", expand=True)
        columns = ("title", "due_at", "status")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("title", text="Заголовок")
        self.tree.heading("due_at", text="Дата и время")
        self.tree.heading("status", text="Статус")
        self.tree.column("title", width=380)
        self.tree.column("due_at", width=150, anchor="center")
        self.tree.column("status", width=120, anchor="center")
        for status, color in ROW_COLORS.items():
            self.tree.tag_configure(status, foreground=color)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_details())
        self.tree.bind("<Delete>", lambda e: self.delete_reminder())
        self.tree.bind("<BackSpace>", lambda e: self.delete_reminder())

        details = ttk.LabelFrame(self.root, text="Описание", padding=8)
        details.pack(fill="x", padx=10)
        self.details_var = tk.StringVar()
        ttk.Label(details, textvariable=self.details_var, wraplength=700,
                  justify="left").pack(anchor="w")

        actions = ttk.Frame(self.root, padding=10)
        actions.pack(fill="x")
        ttk.Button(actions, text="✓ Готово",
                   command=lambda: self.change_status(STATUS_DONE)).pack(side="left")
        ttk.Button(actions, text="✕ Отменить",
                   command=lambda: self.change_status(STATUS_CANCELLED)).pack(side="left", padx=6)
        ttk.Button(actions, text="Удалить", command=self.delete_reminder).pack(side="left")
        ttk.Label(actions, text="Закрытие окна сворачивает его; выход — ⌘Q",
                  foreground="gray").pack(side="right")

    # --- Данные ---------------------------------------------------------------

    def _current_filter(self) -> str | None:
        label = self.filter_var.get()
        for code, text in STATUS_LABELS.items():
            if text == label:
                return code
        return None

    def refresh(self) -> None:
        selected = self._selected_id()
        self.tree.delete(*self.tree.get_children())
        for r in self.db.get_all(self._current_filter()):
            self.tree.insert("", "end", iid=str(r.id), tags=(r.status,),
                             values=(r.title, r.due_at.strftime("%d.%m.%Y %H:%M"), r.status_label))
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
        self._show_details()

    def _selected_id(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _show_details(self) -> None:
        rid = self._selected_id()
        reminder = self.db.get(rid) if rid is not None else None
        if reminder is None:
            self.details_var.set("")
        else:
            self.details_var.set(reminder.description or "— нет описания —")

    # --- Действия -------------------------------------------------------------

    def add_reminder(self) -> None:
        def save(title, description, due_at):
            new_id = self.db.add(title, description, due_at)
            self.refresh()
            if self.tree.exists(str(new_id)):
                self.tree.selection_set(str(new_id))
                self.tree.see(str(new_id))

        AddReminderDialog(self.root, save)

    def change_status(self, status: str) -> None:
        rid = self._selected_id()
        if rid is None:
            messagebox.showinfo("Напоминалка", "Выберите напоминание в списке.")
            return
        self.db.set_status(rid, status)
        self.scheduler.close_popup(rid)
        self.refresh()

    def delete_reminder(self) -> None:
        rid = self._selected_id()
        if rid is None:
            messagebox.showinfo("Напоминалка", "Выберите напоминание в списке.")
            return
        reminder = self.db.get(rid)
        if reminder and messagebox.askyesno("Удаление", f"Удалить «{reminder.title}»?"):
            self.db.delete(rid)
            self.scheduler.close_popup(rid)
            self.refresh()

    def _restore(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def quit(self) -> None:
        self.root.destroy()
