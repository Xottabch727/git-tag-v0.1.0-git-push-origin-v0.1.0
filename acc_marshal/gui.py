"""Окно программы (tkinter). Логика вынесена в core/commands/remote/storage."""
import csv
import queue
import sys
import threading
import time
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, commands, core, remote, storage

APP_TITLE = "ACC Marshal"


class App:
    def __init__(self, root):
        self.root = root
        root.title("%s %s" % (APP_TITLE, __version__))
        root.geometry("1120x780")
        root.minsize(940, 640)

        self.cfg = storage.load_config()
        self.decisions = storage.load_log()
        self.backend = None
        self.cars_q, self.cars_r = [], []
        self.entry = None
        self.grid = []
        self.results = []
        self.q_files, self.r_files = [], []
        self.jobs = queue.Queue()
        self.status_var = tk.StringVar(value="Подключитесь к серверу на вкладке «Подключение».")

        self._style()
        self._build()
        self._poll()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._mode_changed()
        self._refresh_log()
        if self._has_connection_settings():
            self.connect()

    # ------------------------------------------------------------ общее --
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("vista" if sys.platform == "win32" else "clam")
        except tk.TclError:
            pass
        try:
            from tkinter import font as tkfont
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                tkfont.nametofont(name).configure(size=11)
        except Exception:
            pass
        st.configure("Treeview", rowheight=26)
        st.configure("Big.TButton", padding=(16, 9))

    def status(self, text):
        self.status_var.set(text)

    def show_error(self, err):
        self.status("Ошибка: %s" % err)
        messagebox.showerror("ACC Marshal", str(err))

    def bg(self, fn, done=None):
        """Выполняет fn в потоке, результат отдаёт в главный поток через очередь."""
        def work():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                self.jobs.put((self.show_error, (e,)))
                return
            if done:
                self.jobs.put((done, (res,)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                fn, args = self.jobs.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def copy_text(self, text, note=None):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status(note or "Скопировано в буфер обмена.")

    def roster(self):
        """Номер → имя пилота по загруженным результатам."""
        names = {}
        for cars in (self.cars_r, self.cars_q):
            for c in cars:
                names.setdefault(c["num"], c["name"])
        return names

    def on_close(self):
        self._collect_conn()
        storage.save_config(self.cfg)
        self.root.destroy()

    # ------------------------------------------------------------ окно --
    def _build(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.nb = nb
        self.tab_conn, self.tab_pen, self.tab_grid, self.tab_res, self.tab_ann = (
            ttk.Frame(nb) for _ in range(5))
        nb.add(self.tab_conn, text="Подключение")
        nb.add(self.tab_pen, text="Штрафы")
        nb.add(self.tab_grid, text="Решётка")
        nb.add(self.tab_res, text="Итоги гонки")
        nb.add(self.tab_ann, text="Объявления")
        self._build_conn(self.tab_conn)
        self._build_pen(self.tab_pen)
        self._build_grid(self.tab_grid)
        self._build_res(self.tab_res)
        self._build_ann(self.tab_ann)
        ttk.Label(self.root, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=12, pady=(0, 8))

    # ------------------------------------------------------ подключение --
    def _has_connection_settings(self):
        if self.cfg["backend"] == "local":
            return bool(self.cfg["local_path"])
        return bool(self.cfg["remote"]["host"]) and bool(self.cfg["remote"]["password"])

    def _build_conn(self, f):
        c = self.cfg
        self.mode_var = tk.StringVar(value=c["backend"])
        self.local_var = tk.StringVar(value=c["local_path"])
        r = c["remote"]
        self.host_var = tk.StringVar(value=r["host"])
        self.port_var = tk.StringVar(value=str(r["port"]))
        self.user_var = tk.StringVar(value=r["user"])
        self.pwd_var = tk.StringVar(value=r["password"])
        self.root_var = tk.StringVar(value=r["root"])
        self.remember_var = tk.BooleanVar(value=bool(r["remember_password"]))

        box = ttk.LabelFrame(f, text="Где лежит сервер")
        box.pack(fill="x", padx=12, pady=12)
        for text, val in (("Папка на этом компьютере", "local"), ("FTP", "ftp"),
                          ("FTP с шифрованием (FTPS)", "ftps"), ("SFTP", "sftp")):
            ttk.Radiobutton(box, text=text, value=val, variable=self.mode_var,
                            command=self._mode_changed).pack(anchor="w", padx=10, pady=2)

        self.local_frame = ttk.LabelFrame(f, text="Папка сервера (где лежат cfg и results)")
        self.local_frame.columnconfigure(0, weight=1)
        ttk.Entry(self.local_frame, textvariable=self.local_var).grid(
            row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(self.local_frame, text="Обзор…", command=self.pick_local).grid(
            row=0, column=1, padx=8, pady=8)

        self.remote_frame = ttk.LabelFrame(f, text="Доступ к хостингу (данные из панели хостинга)")
        rf = self.remote_frame
        rf.columnconfigure(1, weight=1)
        rows = (("Адрес", self.host_var, None), ("Порт (пусто — стандартный)", self.port_var, None),
                ("Логин", self.user_var, None), ("Пароль", self.pwd_var, "*"),
                ("Папка сервера на хостинге", self.root_var, None))
        for i, (label, var, show) in enumerate(rows):
            ttk.Label(rf, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(rf, textvariable=var, show=show or "").grid(
                row=i, column=1, sticky="ew", padx=8, pady=4)
        ttk.Checkbutton(rf, text="Запомнить пароль (хранится в открытом виде в файле настроек)",
                        variable=self.remember_var).grid(
            row=len(rows), column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(rf, text="«Папка сервера» — путь на хостинге, где лежат cfg и results "
                           "(например /server). Если они в корне, оставьте пустым.",
                  wraplength=700, justify="left").grid(
            row=len(rows) + 1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        self.btn_connect = ttk.Button(f, text="Подключиться", style="Big.TButton",
                                      command=self.connect)
        self.btn_connect.pack(anchor="w", padx=12, pady=12)

    def _mode_changed(self):
        self.local_frame.pack_forget()
        self.remote_frame.pack_forget()
        if self.mode_var.get() == "local":
            self.local_frame.pack(fill="x", padx=12, pady=6, before=self.btn_connect)
        else:
            self.remote_frame.pack(fill="x", padx=12, pady=6, before=self.btn_connect)

    def pick_local(self):
        d = filedialog.askdirectory(title="Папка сервера ACC (где лежат cfg и results)")
        if d:
            self.local_var.set(d)

    def _collect_conn(self):
        self.cfg["backend"] = self.mode_var.get()
        self.cfg["local_path"] = self.local_var.get().strip()
        self.cfg["remote"] = {
            "host": self.host_var.get().strip(), "port": self.port_var.get().strip(),
            "user": self.user_var.get().strip(), "password": self.pwd_var.get(),
            "root": self.root_var.get().strip(),
            "remember_password": bool(self.remember_var.get()),
        }

    def connect(self):
        self._collect_conn()
        try:
            b = remote.make_backend(self.cfg)
        except Exception as e:  # noqa: BLE001
            self.show_error(e)
            return
        storage.save_config(self.cfg)
        self.status("Подключаюсь…")

        def done(info):
            self.backend = b
            self.status(info)
            self.refresh_files()

        self.bg(b.check, done)

    def refresh_files(self):
        b = self.backend
        if not b:
            self.status("Сначала подключитесь к серверу.")
            return

        def work():
            qs, rs = b.list_results("_Q.json"), b.list_results("_R.json")
            raw = b.read_optional("cfg/entrylist.json")
            entry = core.loads_acc_json(raw) if raw else None
            return qs, rs, entry

        def done(res):
            self.q_files, self.r_files, self.entry = res
            self.q_combo["values"] = self.q_files
            self.r_combo["values"] = self.r_files
            if self.q_files:
                self.q_var.set(self.q_files[0])
                self.load_quali()
            if self.r_files:
                self.r_var.set(self.r_files[0])
                self.load_race()
            self.status("Найдено: квалификаций %d, гонок %d. Entrylist: %s." % (
                len(self.q_files), len(self.r_files), "есть" if self.entry else "нет"))

        self.bg(work, done)

    def _load_session(self, name, setter):
        b = self.backend
        if not b or not name:
            return

        def work():
            return core.parse_session(core.loads_acc_json(b.read("results/" + name)))

        def done(cars):
            setter(cars)
            self._on_roster_changed()

        self.bg(work, done)

    # ------------------------------------------------------------ штрафы --
    def _build_pen(self, f):
        self.num_var = tk.StringVar()
        self.kind_var = tk.StringVar(value=commands.KINDS[0]["label"])
        self.val_var = tk.StringVar(value="")
        self.unit_var = tk.StringVar(value="")
        self.reason_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.cmd_var = tk.StringVar()
        self.hint_var = tk.StringVar()

        form = ttk.LabelFrame(f, text="Новое решение")
        form.pack(fill="x", padx=12, pady=(12, 6))
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="№ машины").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.num_entry = ttk.Entry(form, textvariable=self.num_var, width=8)
        self.num_entry.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(form, textvariable=self.name_var).grid(row=0, column=2, columnspan=2,
                                                          sticky="w", padx=8)

        ttk.Label(form, text="Решение").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.kind_combo = ttk.Combobox(form, textvariable=self.kind_var, state="readonly",
                                       values=[k["label"] for k in commands.KINDS], width=34)
        self.kind_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=8)
        self.kind_combo.bind("<<ComboboxSelected>>", lambda e: self._kind_selected())
        self.val_spin = ttk.Spinbox(form, from_=1, to=999, width=6, textvariable=self.val_var)
        self.val_spin.grid(row=1, column=3, sticky="w", padx=8)
        ttk.Label(form, textvariable=self.unit_var).grid(row=1, column=4, sticky="w")

        ttk.Label(form, text="Причина").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.reason_entry = ttk.Entry(form, textvariable=self.reason_var)
        self.reason_entry.grid(row=2, column=1, columnspan=4, sticky="ew", padx=8)

        ttk.Label(form, text="Команда для чата").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        self.cmd_entry = ttk.Entry(form, textvariable=self.cmd_var, state="readonly",
                                   font=("Consolas", 16))
        self.cmd_entry.grid(row=3, column=1, columnspan=3, sticky="ew", padx=8)
        ttk.Button(form, text="Скопировать", command=self.copy_current_cmd).grid(
            row=3, column=4, padx=8)
        ttk.Label(form, textvariable=self.hint_var, foreground="#6b6f73").grid(
            row=4, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 6))

        ttk.Button(form, text="Добавить в журнал и скопировать команду (Ctrl+Enter)",
                   style="Big.TButton", command=self.add_decision).grid(
            row=5, column=0, columnspan=5, sticky="w", padx=8, pady=(2, 10))

        for var in (self.num_var, self.val_var):
            var.trace_add("write", lambda *a: self._pen_changed())
        for w in (self.num_entry, self.reason_entry, self.val_spin):
            w.bind("<Control-Return>", lambda e: self.add_decision())
        self._kind_selected()

        logbox = ttk.LabelFrame(f, text="Журнал решений")
        logbox.pack(fill="both", expand=True, padx=12, pady=6)
        cols = ("time", "num", "name", "dec", "reason", "cmd")
        heads = ("Время", "№", "Пилот", "Решение", "Причина", "Команда")
        widths = (70, 50, 170, 200, 260, 120)
        self.log_tree = ttk.Treeview(logbox, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.log_tree.heading(c, text=h)
            self.log_tree.column(c, width=w, anchor="center" if c in ("time", "num") else "w")
        sb = ttk.Scrollbar(logbox, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=sb.set)
        self.log_tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb.pack(side="left", fill="y", pady=6)
        bf = ttk.Frame(logbox)
        bf.pack(side="left", fill="y", padx=8, pady=6)
        for text, cmd in (("Скопировать команду", self.copy_selected_cmd),
                          ("Команда отмены", self.copy_selected_undo),
                          ("Удалить запись", self.delete_selected),
                          ("Новый уикенд…", self.new_weekend)):
            ttk.Button(bf, text=text, command=cmd).pack(fill="x", pady=3)

    def _num(self):
        try:
            n = int(self.num_var.get().strip())
        except ValueError:
            return None
        return n if n >= 0 else None

    def kind_spec(self):
        return commands.KIND_BY_LABEL[self.kind_var.get()]

    def _kind_selected(self):
        spec = self.kind_spec()
        if "value" in spec:
            self.val_spin.state(["!disabled"])
            self.val_var.set(str(spec.get("default", 1)))
            self.unit_var.set(spec["value"])
        else:
            self.val_var.set("")
            self.unit_var.set("")
            self.val_spin.state(["disabled"])
        self._pen_changed()

    def _pen_changed(self):
        spec = self.kind_spec()
        num = self._num()
        self.name_var.set(self.roster().get(num, "") if num is not None else "")
        cmd = commands.build_command(spec["key"], num, self.cfg["commands"]) if num is not None else None
        if self.cfg.get("translit") and cmd:
            cmd = commands.translit(cmd)
        self.cmd_var.set(cmd or "")
        self.hint_var.set("" if spec.get("cmd") else spec.get("hint", ""))

    def copy_current_cmd(self):
        cmd = self.cmd_var.get()
        if cmd:
            self.copy_text(cmd, "Скопировано: %s — вставьте в чат игры." % cmd)
        else:
            self.status("Для этого решения команды нет.")

    def add_decision(self):
        num = self._num()
        if num is None:
            messagebox.showwarning("ACC Marshal", "Укажите номер машины.")
            return
        spec = self.kind_spec()
        value = None
        if "value" in spec:
            try:
                value = int(self.val_var.get())
                if value < 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("ACC Marshal", "Значение должно быть целым числом больше нуля.")
                return
        d = {
            "id": uuid.uuid4().hex[:8],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "num": num,
            "name": self.roster().get(num, ""),
            "kind": spec["key"],
            "value": value,
            "reason": self.reason_var.get().strip(),
        }
        self.decisions.append(d)
        storage.save_log(self.decisions)
        self._decisions_changed()
        cmd = self.cmd_var.get()
        if cmd:
            self.copy_text(cmd, "Записано. Команда скопирована: %s — вставьте в чат игры." % cmd)
        else:
            self.status("Записано в журнал: #%s — %s." % (num, commands.describe_decision(d)))
        self.reason_var.set("")
        self.num_entry.focus_set()

    def _selected_decision(self):
        sel = self.log_tree.selection()
        if not sel:
            self.status("Выберите запись в журнале.")
            return None
        for d in self.decisions:
            if d["id"] == sel[0]:
                return d
        return None

    def _cmd_for(self, d):
        cmd = commands.build_command(d["kind"], d["num"], self.cfg["commands"])
        if self.cfg.get("translit") and cmd:
            cmd = commands.translit(cmd)
        return cmd

    def copy_selected_cmd(self):
        d = self._selected_decision()
        if not d:
            return
        cmd = self._cmd_for(d)
        if cmd:
            self.copy_text(cmd, "Скопировано: %s" % cmd)
        else:
            self.status("Для этого решения команды нет.")

    def copy_selected_undo(self):
        d = self._selected_decision()
        if d:
            cmd = commands.undo_command(d["num"], self.cfg["commands"])
            self.copy_text(cmd, "Скопировано: %s — снимает штрафы с этой машины." % cmd)

    def delete_selected(self):
        d = self._selected_decision()
        if not d:
            return
        if messagebox.askyesno("ACC Marshal", "Удалить запись: #%s — %s?" % (
                d["num"], commands.describe_decision(d))):
            self.decisions = [x for x in self.decisions if x["id"] != d["id"]]
            storage.save_log(self.decisions)
            self._decisions_changed()

    def new_weekend(self):
        if not self.decisions:
            self.status("Журнал уже пуст.")
            return
        if messagebox.askyesno("ACC Marshal", "Очистить журнал решений? "
                                              "Копия будет сохранена в архивный файл."):
            path = storage.archive_log(self.decisions)
            self.decisions = []
            storage.save_log(self.decisions)
            self._decisions_changed()
            self.status("Журнал очищен, архив: %s" % path)

    def _decisions_changed(self):
        self._refresh_log()
        self.refresh_grid()
        self.refresh_results()

    def _refresh_log(self):
        tree = self.log_tree
        tree.delete(*tree.get_children())
        for d in reversed(self.decisions):
            tree.insert("", "end", iid=d["id"], values=(
                d["ts"][11:], d["num"], d.get("name", ""), commands.describe_decision(d),
                d.get("reason", ""), self._cmd_for(d) or ""))

    def _on_roster_changed(self):
        self._pen_changed()
        self.refresh_grid()
        self.refresh_results()

    # ----------------------------------------------------------- решётка --
    def _build_grid(self, f):
        self.q_var = tk.StringVar()
        self.rev_var = tk.StringVar(value="0")
        self.r107_var = tk.BooleanVar(value=False)

        top = ttk.Frame(f)
        top.pack(fill="x", padx=12, pady=(12, 4))
        ttk.Label(top, text="Квалификация").pack(side="left")
        self.q_combo = ttk.Combobox(top, textvariable=self.q_var, state="readonly", width=34)
        self.q_combo.pack(side="left", padx=8)
        self.q_combo.bind("<<ComboboxSelected>>", lambda e: self.load_quali())
        ttk.Button(top, text="Обновить с сервера", command=self.refresh_files).pack(side="left")

        rules = ttk.Frame(f)
        rules.pack(fill="x", padx=12, pady=4)
        ttk.Label(rules, text="Реверс топ-N (0 — выкл.)").pack(side="left")
        rv = ttk.Spinbox(rules, from_=0, to=60, width=5, textvariable=self.rev_var,
                         command=self.refresh_grid)
        rv.pack(side="left", padx=8)
        rv.bind("<KeyRelease>", lambda e: self.refresh_grid())
        ttk.Checkbutton(rules, text="Правило 107% → пит-лейн", variable=self.r107_var,
                        command=self.refresh_grid).pack(side="left", padx=16)

        cols = ("q", "num", "name", "best", "pen", "start")
        heads = ("Квал.", "№", "Пилот", "Лучший круг", "Штраф", "Старт")
        widths = (60, 50, 260, 110, 90, 150)
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, padx=12, pady=6)
        self.grid_tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.grid_tree.heading(c, text=h)
            self.grid_tree.column(c, width=w, anchor="w" if c == "name" else "center")
        self.grid_tree.tag_configure("pen", foreground="#b3261e")
        self.grid_tree.tag_configure("pit", foreground="#8a5a00")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.grid_tree.yview)
        self.grid_tree.configure(yscrollcommand=sb.set)
        self.grid_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        bot = ttk.Frame(f)
        bot.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(bot, text="Назначить штраф выбранному…", command=self.grid_add_penalty).pack(side="left")
        ttk.Button(bot, text="Скопировать решётку", command=self.copy_grid).pack(side="left", padx=8)
        ttk.Button(bot, text="Сохранить файл…", command=self.save_entry_as).pack(side="left")
        ttk.Button(bot, text="Залить на сервер", style="Big.TButton",
                   command=self.upload_entrylist).pack(side="right")

    def load_quali(self):
        self._load_session(self.q_var.get(), lambda cars: setattr(self, "cars_q", cars))

    def refresh_grid(self):
        if not self.cars_q:
            return
        try:
            rev = max(0, int(self.rev_var.get() or 0))
        except ValueError:
            rev = 0
        pen = core.grid_pen_from_decisions(self.decisions)
        self.grid = core.compute_grid(self.cars_q, pen, rev, self.r107_var.get())
        tree = self.grid_tree
        tree.delete(*tree.get_children())
        for i, c in enumerate(self.cars_q):
            g = next(x for x in self.grid if x["row"]["num"] == c["num"])
            if g["pit"]:
                start = "P%d  пит-лейн" % g["pos"]
            elif g["delta"] > 0:
                start = "P%d  ▼%d" % (g["pos"], g["delta"])
            elif g["delta"] < 0:
                start = "P%d  ▲%d" % (g["pos"], -g["delta"])
            else:
                start = "P%d" % g["pos"]
            pen_txt = ("−%d" % g["penalty"]) if g["penalty"] else ""
            tags = ("pit",) if g["pit"] else (("pen",) if g["penalty"] else ())
            tree.insert("", "end", iid=str(i), tags=tags, values=(
                "P%d" % (i + 1), c["num"], c["name"], core.fmt_lap(c["best"]), pen_txt, start))

    def grid_add_penalty(self):
        sel = self.grid_tree.selection()
        if not sel:
            self.status("Выберите пилота в таблице.")
            return
        car = self.cars_q[int(sel[0])]
        self.num_var.set(str(car["num"]))
        self.kind_var.set(commands.KIND_BY_KEY["grid"]["label"])
        self._kind_selected()
        self.nb.select(self.tab_pen)
        self.reason_entry.focus_set()

    def copy_grid(self):
        if self.grid:
            self.copy_text(core.grid_text(self.grid), "Решётка скопирована.")

    def _entry_bytes(self):
        obj, missing = core.build_entrylist(self.grid, self.entry)
        return obj, missing, core.dumps_acc_json(obj)

    def save_entry_as(self):
        if not self.grid:
            self.status("Сначала загрузите результаты квалификации.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="entrylist.json",
                                         filetypes=[("JSON", "*.json")])
        if p:
            _, _, data = self._entry_bytes()
            with open(p, "wb") as fh:
                fh.write(data)
            self.status("Сохранено: %s" % p)

    def upload_entrylist(self):
        if not self.grid:
            self.status("Сначала загрузите результаты квалификации.")
            return
        b = self.backend
        if not b:
            self.status("Сначала подключитесь к серверу.")
            return
        obj, missing, data = self._entry_bytes()
        if not messagebox.askyesno(
                "ACC Marshal",
                "Записать решётку в cfg/entrylist.json на сервере?\n\n"
                "Старая версия сохранится рядом как резервная копия. "
                "После этого перезапустите сервер через панель хостинга."):
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")

        def work():
            old = b.read_optional("cfg/entrylist.json")
            if old:
                b.write("cfg/entrylist_backup_%s.json" % stamp, old)
            b.write("cfg/entrylist.json", data)

        def done(_):
            self.entry = obj
            msg = "Решётка загружена. Перезапустите сервер через панель хостинга."
            if missing:
                msg += " Записей без пилота в квалификации: %d (их позиции не менялись)." % missing
            self.status(msg)

        self.status("Загружаю…")
        self.bg(work, done)

    # ------------------------------------------------------ итоги гонки --
    def _build_res(self, f):
        self.r_var = tk.StringVar()
        top = ttk.Frame(f)
        top.pack(fill="x", padx=12, pady=(12, 4))
        ttk.Label(top, text="Гонка").pack(side="left")
        self.r_combo = ttk.Combobox(top, textvariable=self.r_var, state="readonly", width=34)
        self.r_combo.pack(side="left", padx=8)
        self.r_combo.bind("<<ComboboxSelected>>", lambda e: self.load_race())
        ttk.Button(top, text="Обновить с сервера", command=self.refresh_files).pack(side="left")

        ttk.Label(f, text="Штрафы, выданные командами во время гонки, сервер уже учёл в результатах. "
                          "Здесь добавляются только решения «к итогам гонки» и «дисквалификация по итогам».",
                  wraplength=900, justify="left", foreground="#6b6f73").pack(
            fill="x", padx=12, pady=4)

        cols = ("pos", "num", "name", "laps", "total", "pen", "delta")
        heads = ("Итог", "№", "Пилот", "Круги", "Время", "Штраф", "Изм.")
        widths = (70, 50, 260, 70, 130, 80, 70)
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, padx=12, pady=6)
        self.res_tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.res_tree.heading(c, text=h)
            self.res_tree.column(c, width=w, anchor="w" if c == "name" else "center")
        self.res_tree.tag_configure("pen", foreground="#b3261e")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.res_tree.yview)
        self.res_tree.configure(yscrollcommand=sb.set)
        self.res_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

        bot = ttk.Frame(f)
        bot.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(bot, text="Назначить штраф выбранному…", command=self.res_add_penalty).pack(side="left")
        ttk.Button(bot, text="Скопировать итоги", command=self.copy_results).pack(side="left", padx=8)
        ttk.Button(bot, text="Сохранить CSV…", command=self.save_results_csv).pack(side="left")

    def load_race(self):
        self._load_session(self.r_var.get(), lambda cars: setattr(self, "cars_r", cars))

    def refresh_results(self):
        if not self.cars_r:
            return
        self.results = core.classify(self.cars_r, self.decisions)
        tree = self.res_tree
        tree.delete(*tree.get_children())
        for i, r in enumerate(self.results):
            c = r["row"]
            pos = "DSQ" if r["dsq"] else "P%d" % r["pos"]
            delta = "" if r["dsq"] or not r["delta"] else (
                "▲%d" % r["delta"] if r["delta"] > 0 else "▼%d" % -r["delta"])
            pen = ("+%d с" % r["penalty_s"]) if r["penalty_s"] else ("DSQ" if r["dsq"] else "")
            tree.insert("", "end", iid=str(i), tags=("pen",) if pen else (), values=(
                pos, c["num"], c["name"], c["laps"], core.fmt_total(r["total_final"]), pen, delta))

    def res_add_penalty(self):
        sel = self.res_tree.selection()
        if not sel:
            self.status("Выберите пилота в таблице.")
            return
        car = self.results[int(sel[0])]["row"]
        self.num_var.set(str(car["num"]))
        self.kind_var.set(commands.KIND_BY_KEY["post_time"]["label"])
        self._kind_selected()
        self.nb.select(self.tab_pen)
        self.reason_entry.focus_set()

    def copy_results(self):
        if self.results:
            self.copy_text(core.classification_text(self.results), "Итоги скопированы.")

    def save_results_csv(self):
        if not self.results:
            self.status("Сначала загрузите результаты гонки.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="results.csv",
                                         filetypes=[("CSV", "*.csv")])
        if p:
            with open(p, "w", newline="", encoding="utf-8-sig") as fh:
                csv.writer(fh, delimiter=";").writerows(core.classification_rows_csv(self.results))
            self.status("Сохранено: %s" % p)

    # -------------------------------------------------------- объявления --
    def _build_ann(self, f):
        self.ann_num_var = tk.StringVar()
        self.ann_reason_var = tk.StringVar()
        self.translit_var = tk.BooleanVar(value=bool(self.cfg.get("translit")))
        self.templates = self.cfg["announcements"]

        left = ttk.Frame(f)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        ttk.Label(left, text="Шаблон").pack(anchor="w")
        self.ann_list = tk.Listbox(left, height=14, width=34, exportselection=False,
                                   font=("TkDefaultFont", 11))
        for title, _ in self.templates:
            self.ann_list.insert("end", title)
        self.ann_list.pack(fill="y", expand=True, pady=4)
        self.ann_list.bind("<<ListboxSelect>>", lambda e: self._ann_render())

        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)
        row = ttk.Frame(right)
        row.pack(fill="x")
        ttk.Label(row, text="№ машины").pack(side="left")
        ttk.Entry(row, textvariable=self.ann_num_var, width=7).pack(side="left", padx=8)
        ttk.Label(row, text="Причина / комментарий").pack(side="left")
        ttk.Entry(row, textvariable=self.ann_reason_var).pack(side="left", fill="x", expand=True, padx=8)
        for var in (self.ann_num_var, self.ann_reason_var):
            var.trace_add("write", lambda *a: self._ann_render())
        ttk.Checkbutton(right, text="Транслитом (если чат игры не показывает кириллицу)",
                        variable=self.translit_var, command=self._translit_changed).pack(
            anchor="w", pady=6)
        self.ann_text = tk.Text(right, height=8, wrap="word", font=("TkDefaultFont", 13))
        self.ann_text.pack(fill="both", expand=True, pady=4)
        ttk.Button(right, text="Скопировать в буфер", style="Big.TButton",
                   command=self.copy_announcement).pack(anchor="w", pady=8)

    def _translit_changed(self):
        self.cfg["translit"] = bool(self.translit_var.get())
        self._ann_render()
        self._pen_changed()
        self._refresh_log()

    def _ann_render(self):
        sel = self.ann_list.curselection()
        if not sel:
            return
        _, text = self.templates[sel[0]]
        try:
            num = int(self.ann_num_var.get().strip())
        except ValueError:
            num = ""
        name = self.roster().get(num, "") if num != "" else ""
        out = commands.render(text, num=num, name=name, reason=self.ann_reason_var.get().strip())
        if self.translit_var.get():
            out = commands.translit(out)
        self.ann_text.delete("1.0", "end")
        self.ann_text.insert("1.0", out)

    def copy_announcement(self):
        text = self.ann_text.get("1.0", "end").strip()
        if text:
            self.copy_text(text, "Объявление скопировано — вставьте в чат игры.")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
