import ftplib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acc_marshal import remote, storage
from tests import helpers


class FakeFTP:
    files = {}
    last = None

    def __init__(self):
        FakeFTP.last = self
        self.cwd_to = ""
        self.closed = False

    def connect(self, host, port, timeout=0):
        self.host, self.port = host, port

    def login(self, user, pwd):
        if pwd != "secret":
            raise ftplib.error_perm("530 bad login")

    def prot_p(self):
        pass

    def cwd(self, d):
        self.cwd_to = d.strip("/")

    def _full(self, rel):
        return (self.cwd_to + "/" if self.cwd_to else "") + rel

    def nlst(self, d):
        pre = self._full(d) + "/"
        return [k for k in FakeFTP.files if k.startswith(pre)]

    def retrbinary(self, cmd, cb):
        key = self._full(cmd[5:])
        if key not in FakeFTP.files:
            raise ftplib.error_perm("550 not found")
        cb(FakeFTP.files[key])

    def storbinary(self, cmd, fp):
        FakeFTP.files[self._full(cmd[5:])] = fp.read()

    def quit(self):
        self.closed = True


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "results").mkdir()
        (self.root / "cfg").mkdir()
        (self.root / "results" / "240101_100000_Q.json").write_bytes(helpers.session_bytes(helpers.quali_lines()))
        (self.root / "results" / "240102_100000_Q.json").write_bytes(helpers.session_bytes(helpers.quali_lines()))
        (self.root / "results" / "240102_110000_R.json").write_bytes(helpers.session_bytes(helpers.race_lines(), "R"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_newest_first(self):
        b = remote.LocalBackend(self.root)
        self.assertEqual(b.list_results("_Q.json"), ["240102_100000_Q.json", "240101_100000_Q.json"])
        self.assertEqual(b.list_results("_R.json"), ["240102_110000_R.json"])

    def test_accepts_cfg_subfolder(self):
        b = remote.LocalBackend(self.root / "cfg")
        self.assertEqual(b.root, self.root)

    def test_read_write_optional(self):
        b = remote.LocalBackend(self.root)
        self.assertIsNone(b.read_optional("cfg/entrylist.json"))
        b.write("cfg/entrylist.json", b"abc")
        self.assertEqual(b.read("cfg/entrylist.json"), b"abc")
        self.assertIn("entrylist.json: найден", b.check())

    def test_make_backend_errors(self):
        with self.assertRaises(ValueError):
            remote.make_backend({"backend": "local", "local_path": ""})
        with self.assertRaises(ValueError):
            remote.make_backend({"backend": "ftp", "remote": {"host": ""}})
        b = remote.make_backend({"backend": "local", "local_path": str(self.root)})
        self.assertIsInstance(b, remote.LocalBackend)


class FtpTests(unittest.TestCase):
    def setUp(self):
        FakeFTP.files = {
            "srv/results/240102_100000_Q.json": b"q2",
            "srv/results/240101_100000_Q.json": b"q1",
            "srv/results/240102_110000_R.json": b"r",
        }
        self.patch = mock.patch.object(ftplib, "FTP", FakeFTP)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def backend(self, pwd="secret"):
        return remote.make_backend({"backend": "ftp", "remote": {
            "host": "h", "port": "", "user": "u", "password": pwd, "root": "/srv"}})

    def test_list_and_read(self):
        b = self.backend()
        self.assertEqual(b.list_results("_Q.json"), ["240102_100000_Q.json", "240101_100000_Q.json"])
        self.assertEqual(b.read("results/240102_110000_R.json"), b"r")
        self.assertTrue(FakeFTP.last.closed)
        self.assertEqual(FakeFTP.last.port, 21)

    def test_write_and_optional(self):
        b = self.backend()
        self.assertIsNone(b.read_optional("cfg/entrylist.json"))
        b.write("cfg/entrylist.json", b"new")
        self.assertEqual(FakeFTP.files["srv/cfg/entrylist.json"], b"new")
        self.assertEqual(b.read_optional("cfg/entrylist.json"), b"new")

    def test_bad_password(self):
        with self.assertRaises(ftplib.error_perm):
            self.backend("wrong").list_results("_Q.json")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"ACC_MARSHAL_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_defaults_and_merge(self):
        cfg = storage.load_config()
        self.assertEqual(cfg["backend"], "local")
        self.assertEqual(cfg["commands"]["tp5"], "/tp5 {num}")
        (Path(self.tmp.name) / "config.json").write_text('{"commands": {"tp5": "/x {num}"}}', encoding="utf-8")
        cfg = storage.load_config()
        self.assertEqual(cfg["commands"]["tp5"], "/x {num}")
        self.assertEqual(cfg["commands"]["dt"], "/dt {num}")

    def test_password_not_saved_by_default(self):
        cfg = storage.load_config()
        cfg["remote"]["password"] = "secret"
        storage.save_config(cfg)
        self.assertEqual(storage.load_config()["remote"]["password"], "")
        cfg["remote"]["remember_password"] = True
        storage.save_config(cfg)
        self.assertEqual(storage.load_config()["remote"]["password"], "secret")

    def test_log_and_archive(self):
        self.assertEqual(storage.load_log(), [])
        storage.save_log([{"id": "a", "num": 5}])
        self.assertEqual(storage.load_log()[0]["num"], 5)
        path = storage.archive_log(storage.load_log())
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
