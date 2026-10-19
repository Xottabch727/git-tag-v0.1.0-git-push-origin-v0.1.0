"""Настройки и журнал решений. Хранятся в папке ~/.acc_marshal (или $ACC_MARSHAL_HOME)."""
import copy
import json
import os
import time
from pathlib import Path

from . import commands


def app_dir() -> Path:
    base = os.environ.get("ACC_MARSHAL_HOME")
    p = Path(base) if base else Path.home() / ".acc_marshal"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULT_CONFIG = {
    "backend": "local",          # local | ftp | ftps | sftp
    "local_path": "",
    "remote": {
        "host": "", "port": "", "user": "", "password": "", "root": "",
        "remember_password": False,
    },
    "translit": False,
    "commands": dict(commands.DEFAULT_COMMANDS),
    "announcements": [list(a) for a in commands.DEFAULT_ANNOUNCEMENTS],
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    try:
        data = json.loads((app_dir() / "config.json").read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return _merge(DEFAULT_CONFIG, data)


def save_config(cfg: dict) -> None:
    out = copy.deepcopy(cfg)
    if not out.get("remote", {}).get("remember_password"):
        out["remote"]["password"] = ""
    (app_dir() / "config.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def load_log() -> list:
    try:
        data = json.loads((app_dir() / "log.json").read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_log(decisions: list) -> None:
    (app_dir() / "log.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")


def archive_log(decisions: list):
    """Сохраняет текущий журнал в архивный файл. Возвращает путь к архиву."""
    path = app_dir() / ("log_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
