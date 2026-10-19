"""Доступ к файлам сервера: локальная папка, FTP/FTPS или SFTP.

Пути внутри сервера всегда относительные: "results/..." и "cfg/...".
"""
import ftplib
import io
import posixpath
from pathlib import Path


class Backend:
    label = ""

    def list_results(self, suffix):          # -> [имена файлов], новые первыми
        raise NotImplementedError

    def read(self, rel):                     # -> bytes
        raise NotImplementedError

    def read_optional(self, rel):            # -> bytes | None
        try:
            return self.read(rel)
        except (FileNotFoundError, ftplib.error_perm, OSError):
            return None

    def write(self, rel, data):
        raise NotImplementedError

    def check(self) -> str:
        """Проверка подключения. Возвращает текст для строки статуса или бросает ошибку."""
        names = self.list_results(".json")
        has_cfg = self.read_optional("cfg/entrylist.json") is not None
        return "Подключено (%s). Файлов результатов: %d. entrylist.json: %s." % (
            self.label, len(names), "найден" if has_cfg else "не найден (будет создан)")


def _newest_first(names, suffix):
    suffix = suffix.lower()
    return sorted([n for n in names if n.lower().endswith(suffix)], reverse=True)


# --------------------------------------------------------------- локально --

class LocalBackend(Backend):
    def __init__(self, path):
        root = Path(path)
        # Можно указать и саму папку cfg или results.
        if root.name.lower() in ("cfg", "results") and (root.parent / "cfg").exists():
            root = root.parent
        self.root = root
        self.label = "папка %s" % root

    def list_results(self, suffix):
        d = self.root / "results"
        if not d.is_dir():
            return []
        return _newest_first([p.name for p in d.iterdir() if p.is_file()], suffix)

    def read(self, rel):
        return (self.root / rel).read_bytes()

    def write(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


# -------------------------------------------------------------------- FTP --

class FtpBackend(Backend):
    def __init__(self, host, port=21, user="", password="", root="", tls=False):
        self.host, self.port = host, int(port or 21)
        self.user, self.password, self.root, self.tls = user, password, root, tls
        self.label = "%s://%s" % ("ftps" if tls else "ftp", host)

    def _connect(self):
        ftp = ftplib.FTP_TLS() if self.tls else ftplib.FTP()
        ftp.connect(self.host, self.port, timeout=20)
        ftp.login(self.user, self.password)
        if self.tls:
            ftp.prot_p()
        if self.root:
            ftp.cwd(self.root)
        return ftp

    def list_results(self, suffix):
        ftp = self._connect()
        try:
            try:
                names = [posixpath.basename(n) for n in ftp.nlst("results")]
            except ftplib.error_perm:
                names = []   # некоторые серверы отвечают 550, если папка пустая
        finally:
            _quit(ftp)
        return _newest_first(names, suffix)

    def read(self, rel):
        ftp = self._connect()
        try:
            buf = io.BytesIO()
            ftp.retrbinary("RETR " + rel, buf.write)
            return buf.getvalue()
        finally:
            _quit(ftp)

    def write(self, rel, data):
        ftp = self._connect()
        try:
            ftp.storbinary("STOR " + rel, io.BytesIO(data))
        finally:
            _quit(ftp)


def _quit(ftp):
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


# ------------------------------------------------------------------- SFTP --

class SftpBackend(Backend):
    """Нужен пакет paramiko (pip install paramiko). В тестах разработчика не проверялся
    на живом сервере."""

    def __init__(self, host, port=22, user="", password="", root=""):
        self.host, self.port = host, int(port or 22)
        self.user, self.password, self.root = user, password, root
        self.label = "sftp://%s" % host

    def _open(self):
        try:
            import paramiko
        except ImportError:
            raise RuntimeError("Для SFTP нужен пакет paramiko: pip install paramiko")
        tr = paramiko.Transport((self.host, self.port))
        tr.connect(username=self.user, password=self.password)
        return tr, paramiko.SFTPClient.from_transport(tr)

    def _p(self, rel):
        return posixpath.join(self.root or ".", rel)

    def list_results(self, suffix):
        tr, sftp = self._open()
        try:
            try:
                names = sftp.listdir(self._p("results"))
            except IOError:
                names = []
            return _newest_first(names, suffix)
        finally:
            sftp.close()
            tr.close()

    def read(self, rel):
        tr, sftp = self._open()
        try:
            with sftp.open(self._p(rel), "rb") as f:
                return f.read()
        finally:
            sftp.close()
            tr.close()

    def write(self, rel, data):
        tr, sftp = self._open()
        try:
            with sftp.open(self._p(rel), "wb") as f:
                f.write(data)
        finally:
            sftp.close()
            tr.close()


def make_backend(cfg) -> Backend:
    mode = cfg.get("backend", "local")
    if mode == "local":
        path = (cfg.get("local_path") or "").strip()
        if not path:
            raise ValueError("Не указана папка сервера.")
        if not Path(path).is_dir():
            raise ValueError("Папка не найдена: %s" % path)
        return LocalBackend(path)
    r = cfg.get("remote", {})
    host = (r.get("host") or "").strip()
    if not host:
        raise ValueError("Не указан адрес хостинга.")
    root = (r.get("root") or "").strip()
    if mode in ("ftp", "ftps"):
        return FtpBackend(host, r.get("port") or 21, r.get("user", ""), r.get("password", ""),
                          root, tls=(mode == "ftps"))
    if mode == "sftp":
        return SftpBackend(host, r.get("port") or 22, r.get("user", ""), r.get("password", ""), root)
    raise ValueError("Неизвестный тип подключения: %s" % mode)
