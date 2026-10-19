"""Проверка логики окна без настоящего tkinter: виджеты заменены заглушками.
Это не заменяет запуск программы на Windows, но ловит опечатки и ошибки в обработчиках."""
import importlib
import os
import queue
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests import helpers


class FakeVar:
    def __init__(self, master=None, value=None):
        self._v = value
        self._cbs = []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):
            cb()

    def trace_add(self, mode, cb):
        self._cbs.append(cb)


class FakeStr(FakeVar):
    def __init__(self, master=None, value=""):
        super().__init__(master, "" if value is None else value)


class FakeBool(FakeVar):
    def __init__(self, master=None, value=False):
        super().__init__(master, value)


class FakeTree:
    def __init__(self, *a, **k):
        self.rows = {}
        self.order = []
        self.sel = []

    def insert(self, parent, index, iid=None, values=(), tags=()):
        self.rows[iid] = values
        self.order.append(iid)

    def delete(self, *ids):
        self.rows.clear()
        self.order.clear()

    def get_children(self):
        return list(self.order)

    def selection(self):
        return self.sel

    def __getattr__(self, name):          # heading, column, bind, pack, ...
        return mock.MagicMock()


class FakeText:
    def __init__(self, *a, **k):
        self.t = ""

    def delete(self, *a):
        self.t = ""

    def insert(self, idx, text):
        self.t = text

    def get(self, *a):
        return self.t + "\n"

    def __getattr__(self, name):
        return mock.MagicMock()


class FakeListbox:
    def __init__(self, *a, **k):
        self.items, self.sel = [], ()

    def insert(self, idx, text):
        self.items.append(text)

    def curselection(self):
        return self.sel

    def __getattr__(self, name):
        return mock.MagicMock()


def fake_modules():
    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    tk.StringVar, tk.BooleanVar, tk.TclError = FakeStr, FakeBool, Exception
    tk.Text, tk.Listbox = FakeText, FakeListbox
    tk.Tk = lambda: mock.MagicMock()
    for n in ("Frame", "LabelFrame", "Label", "Entry", "Button", "Notebook", "Combobox",
              "Spinbox", "Radiobutton", "Checkbutton", "Scrollbar", "Style"):
        setattr(ttk, n, lambda *a, **k: mock.MagicMock())
    ttk.Treeview = FakeTree
    fd, mb = types.ModuleType("tkinter.filedialog"), types.ModuleType("tkinter.messagebox")
    mb.askyesno = mock.MagicMock(return_value=True)
    mb.showwarning = mock.MagicMock()
    mb.showerror = mock.MagicMock()
    fd.askdirectory = fd.asksaveasfilename = mock.MagicMock(return_value="")
    tk.ttk, tk.filedialog, tk.messagebox = ttk, fd, mb
    return {"tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": fd, "tkinter.messagebox": mb}


class GuiLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name) / "home"
        self.srv = Path(self.tmp.name) / "srv"
        (self.srv / "results").mkdir(parents=True)
        (self.srv / "cfg").mkdir()
        (self.srv / "results" / "20240101_Q.json").write_bytes(helpers.session_bytes(helpers.quali_lines()))
        (self.srv / "results" / "20240101_R.json").write_bytes(helpers.session_bytes(helpers.race_lines(), "R"))
        import json
        (self.srv / "cfg" / "entrylist.json").write_text(json.dumps({"entries": [
            {"drivers": [{"playerID": "S10"}], "raceNumber": -1, "ballastKg": 5},
            {"drivers": [{"playerID": "S11"}], "raceNumber": -1}], "forceEntryList": 1}), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"ACC_MARSHAL_HOME": str(home)})
        self.env.start()
        self.mods = mock.patch.dict(sys.modules, fake_modules())
        self.mods.start()
        sys.modules.pop("acc_marshal.gui", None)
        self.gui = importlib.import_module("acc_marshal.gui")
        self.addCleanup(lambda: sys.modules.pop("acc_marshal.gui", None))
        self.app = self.gui.App(sys.modules["tkinter"].Tk())

    def tearDown(self):
        self.mods.stop()
        self.env.stop()
        self.tmp.cleanup()

    def pump(self):
        while True:
            try:
                fn, args = self.app.jobs.get(timeout=0.3)
            except queue.Empty:
                return
            fn(*args)

    def connect(self):
        a = self.app
        a.mode_var.set("local")
        a.local_var.set(str(self.srv))
        a.connect()
        self.pump()

    def clipboard(self):
        calls = self.app.root.clipboard_append.call_args_list
        return calls[-1][0][0] if calls else None

    def test_connect_loads_everything(self):
        self.connect()
        a = self.app
        self.assertEqual([c["num"] for c in a.cars_q], [10, 11, 12, 13, 14])
        self.assertEqual(len(a.cars_r), 4)
        self.assertIsNotNone(a.entry)
        self.assertEqual(len(a.grid_tree.order), 5)
        self.assertEqual(len(a.res_tree.order), 4)
        self.assertEqual(a.roster()[12], "Cid C")

    def test_bad_path_shows_error(self):
        a = self.app
        a.mode_var.set("local")
        a.local_var.set("/nonexistent/xyz")
        a.connect()
        sys.modules["tkinter"].messagebox.showerror.assert_called()

    def test_penalty_command_autocopy(self):
        self.connect()
        a = self.app
        a.num_var.set("12")
        a.kind_var.set("+5 сек (в гонке)")
        a._kind_selected()
        self.assertEqual(a.cmd_var.get(), "/tp5 12")
        self.assertEqual(a.name_var.get(), "Cid C")
        a.reason_var.set("contact")
        a.add_decision()
        self.assertEqual(len(a.decisions), 1)
        self.assertEqual(self.clipboard(), "/tp5 12")
        self.assertEqual(a.reason_var.get(), "")
        self.assertEqual(len(a.log_tree.order), 1)

    def test_grid_penalty_flows_to_grid_and_upload(self):
        self.connect()
        a = self.app
        a.num_var.set("10")
        a.kind_var.set("Откат на решётке (мест)")
        a._kind_selected()
        self.assertEqual(a.val_var.get(), "3")
        a.add_decision()
        self.assertEqual([g["row"]["num"] for g in a.grid][:4], [11, 12, 13, 10])
        a.upload_entrylist()
        self.pump()
        import json
        from acc_marshal import core
        new = core.loads_acc_json((self.srv / "cfg" / "entrylist.json").read_bytes())
        self.assertEqual(new["entries"][0]["defaultGridPosition"], 4)
        self.assertEqual(new["entries"][0]["ballastKg"], 5)
        self.assertEqual(new["entries"][1]["defaultGridPosition"], 1)
        backups = list((self.srv / "cfg").glob("entrylist_backup_*.json"))
        self.assertEqual(len(backups), 1)

    def test_post_race_time_changes_results(self):
        self.connect()
        a = self.app
        a.num_var.set("10")
        a.kind_var.set("Секунды к итогам гонки")
        a._kind_selected()
        a.val_var.set("6")
        a.add_decision()
        self.assertEqual([r["row"]["num"] for r in a.results], [11, 10, 12, 13])
        a.copy_results()
        self.assertIn("+6 сек", self.clipboard())

    def test_invalid_number_and_value(self):
        self.connect()
        a = self.app
        a.num_var.set("abc")
        a.add_decision()
        self.assertEqual(a.decisions, [])
        sys.modules["tkinter"].messagebox.showwarning.assert_called()

    def test_delete_undo_and_new_weekend(self):
        self.connect()
        a = self.app
        a.num_var.set("11")
        a.add_decision()
        a.log_tree.sel = [a.decisions[0]["id"]]
        a.copy_selected_undo()
        self.assertEqual(self.clipboard(), "/clear 11")
        a.delete_selected()
        self.assertEqual(a.decisions, [])
        a.num_var.set("12")
        a.add_decision()
        a.new_weekend()
        self.assertEqual(a.decisions, [])

    def test_announcement_render_and_translit(self):
        self.connect()
        a = self.app
        a.ann_list.sel = (8,)          # «Предупреждение пилоту»
        a.ann_num_var.set("12")
        a.ann_reason_var.set("срезал шикану")
        self.assertIn("#12 Cid C: предупреждение. срезал шикану", a.ann_text.t)
        a.translit_var.set(True)
        a._translit_changed()
        self.assertIn("preduprezhdenie", a.ann_text.t)
        a.copy_announcement()
        self.assertIn("preduprezhdenie", self.clipboard())

    def test_grid_add_penalty_shortcut(self):
        self.connect()
        a = self.app
        a.grid_tree.sel = ["2"]
        a.grid_add_penalty()
        self.assertEqual(a.num_var.get(), "12")
        self.assertEqual(a.kind_var.get(), "Откат на решётке (мест)")

    def test_rules_reverse_and_107(self):
        self.connect()
        a = self.app
        a.rev_var.set("3")
        a.refresh_grid()
        self.assertEqual([g["row"]["num"] for g in a.grid][:3], [12, 11, 10])
        a.r107_var.set(True)
        a.refresh_grid()
        self.assertTrue(a.grid[-1]["rule107"])


if __name__ == "__main__":
    unittest.main()
