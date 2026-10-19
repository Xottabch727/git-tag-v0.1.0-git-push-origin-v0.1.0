"""Ядро: чтение файлов результатов ACC, стартовая решётка, итоги гонки со штрафами.

Здесь нет ни GUI, ни сети, поэтому всё покрыто тестами.
"""
import codecs
import copy
import json

NO_TIME = 2147483647


# ------------------------------------------------------------ файлы ACC --

def decode_bytes(data: bytes) -> str:
    """ACC хранит JSON в UTF-16LE; на всякий случай понимаем и UTF-8."""
    if data[:2] == codecs.BOM_UTF16_LE:
        text = data.decode("utf-16-le", errors="replace")
    elif data[:2] == codecs.BOM_UTF16_BE:
        text = data.decode("utf-16-be", errors="replace")
    elif len(data) > 1 and data[1] == 0:
        text = data.decode("utf-16-le", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    return text.lstrip("\ufeff")


def loads_acc_json(data: bytes):
    return json.loads(decode_bytes(data))


def dumps_acc_json(obj) -> bytes:
    """JSON в UTF-16LE с BOM — так файлы читает сервер ACC."""
    text = json.dumps(obj, indent=4, ensure_ascii=False)
    return codecs.BOM_UTF16_LE + text.encode("utf-16-le")


def _ms(value):
    if isinstance(value, (int, float)) and 0 < value < NO_TIME:
        return int(value)
    return None


def parse_meta(data) -> dict:
    return {"type": data.get("sessionType", ""), "track": data.get("trackName", "")}


def parse_session(data) -> list:
    """Список машин в порядке, в котором их отдал сервер (порядок классификации)."""
    lines = (data.get("sessionResult") or {}).get("leaderBoardLines")
    if not isinstance(lines, list) or not lines:
        raise ValueError(
            "В файле нет sessionResult.leaderBoardLines. "
            "Нужен файл результатов сессии (..._Q.json или ..._R.json)."
        )
    cars = []
    for line in lines:
        car = line.get("car") or {}
        cur = line.get("currentDriver") or {}
        drivers = car.get("drivers") or []
        first = drivers[0] if drivers else {}
        name = ("%s %s" % (cur.get("firstName", ""), cur.get("lastName", ""))).strip()
        name = name or cur.get("shortName") or "№%s" % car.get("raceNumber")
        timing = line.get("timing") or {}
        steams = [d.get("playerId") for d in drivers if d.get("playerId")]
        if not steams and cur.get("playerId"):
            steams = [cur["playerId"]]
        cars.append({
            "num": car.get("raceNumber"),
            "model": car.get("carModel", -1),
            "name": name,
            "team": car.get("teamName", ""),
            "steam": first.get("playerId") or cur.get("playerId") or "",
            "steams": steams,
            "best": _ms(timing.get("bestLap")),
            "total": _ms(timing.get("totalTime")),
            "laps": int(timing.get("lapCount") or 0),
        })
    return cars


def fmt_lap(ms) -> str:
    if not ms:
        return "—"
    m, s = divmod(ms / 1000.0, 60)
    return "%d:%06.3f" % (int(m), s)


def fmt_total(ms) -> str:
    if not ms:
        return "—"
    h, rest = divmod(ms / 1000.0, 3600)
    m, s = divmod(rest, 60)
    if h >= 1:
        return "%d:%02d:%06.3f" % (int(h), int(m), s)
    return "%d:%06.3f" % (int(m), s)


# ------------------------------------------------------ стартовая решётка --

def grid_pen_from_decisions(decisions) -> dict:
    """Из журнала решений берём штрафы на решётку: {номер: {"penalty": мест, "pit": bool}}."""
    pen = {}
    for d in decisions:
        if d.get("kind") == "grid":
            p = pen.setdefault(d["num"], {"penalty": 0, "pit": False})
            p["penalty"] += int(d.get("value") or 0)
        elif d.get("kind") == "pit":
            pen.setdefault(d["num"], {"penalty": 0, "pit": False})["pit"] = True
    return pen


def compute_grid(cars, pen, reverse_n=0, rule107=False) -> list:
    """
    cars — порядок по квалификации; pen — {номер: {"penalty": int, "pit": bool}}.
      1. реверс первых N мест (если задан);
      2. штраф в местах: по очереди, начиная с лучшей позиции, откат в уже
         изменённой решётке;
      3. старт с пит-лейна (вручную или по правилу 107%) — в конец решётки.
    """
    base = list(cars)
    n = max(0, min(int(reverse_n or 0), len(base)))
    if n > 1:
        base[:n] = base[:n][::-1]

    times = [r["best"] for r in cars if r["best"]]
    limit = min(times) * 1.07 if (rule107 and times) else None

    pit, by107 = set(), set()
    for r in cars:
        if pen.get(r["num"], {}).get("pit"):
            pit.add(r["num"])
        if limit is not None and (not r["best"] or r["best"] > limit):
            pit.add(r["num"])
            by107.add(r["num"])

    grid = list(base)
    for r in base:
        k = int(pen.get(r["num"], {}).get("penalty", 0) or 0)
        if k > 0 and r["num"] not in pit:
            i = grid.index(r)
            grid.pop(i)
            grid.insert(min(i + k, len(grid)), r)
    for r in base:
        if r["num"] in pit:
            grid.remove(r)
            grid.append(r)

    quali_pos = {r["num"]: i + 1 for i, r in enumerate(cars)}
    out = []
    for i, r in enumerate(grid):
        out.append({
            "row": r,
            "pos": i + 1,
            "delta": (i + 1) - quali_pos[r["num"]],
            "penalty": int(pen.get(r["num"], {}).get("penalty", 0) or 0),
            "pit": r["num"] in pit,
            "rule107": r["num"] in by107,
        })
    return out


def grid_text(grid) -> str:
    lines = []
    for g in grid:
        r = g["row"]
        tail = ""
        if g["rule107"]:
            tail = "  (правило 107%, пит-лейн)"
        elif g["pit"]:
            tail = "  (пит-лейн)"
        elif g["penalty"] > 0:
            tail = "  (штраф −%d)" % g["penalty"]
        lines.append("P%d  #%s  %s%s" % (g["pos"], r["num"], r["name"], tail))
    return "\n".join(lines)


def build_entrylist(grid, existing=None):
    """
    Проставляет defaultGridPosition. Запись в уже существующем entrylist ищется по
    Steam ID пилота, запасной вариант — номер машины. Остальное в файле не трогаем.
    Возвращает (объект, число записей без пилота в этой квалификации).
    """
    by_num = {g["row"]["num"]: g["pos"] for g in grid}
    by_steam = {}
    for g in grid:
        for sid in g["row"].get("steams", []):
            by_steam[sid] = g["pos"]
    if existing and isinstance(existing.get("entries"), list):
        obj = copy.deepcopy(existing)
        missing = 0
        for e in obj["entries"]:
            p = None
            for d in e.get("drivers") or []:
                p = by_steam.get(d.get("playerID"))
                if p:
                    break
            if not p:
                p = by_num.get(e.get("raceNumber"))
            if p:
                e["defaultGridPosition"] = p
            else:
                missing += 1
        return obj, missing
    obj = {
        "entries": [
            {
                "drivers": [{"playerID": g["row"]["steam"]}],
                "raceNumber": g["row"]["num"],
                "forcedCarModel": g["row"]["model"],
                "overrideDriverInfo": 0,
                "defaultGridPosition": g["pos"],
                "ballastKg": 0,
                "restrictor": 0,
            }
            for g in grid
        ],
        "forceEntryList": 1,
    }
    return obj, 0


# --------------------------------------------------------- итоги гонки --

def classify(cars, decisions) -> list:
    """
    Итоги гонки с послегоночными решениями стюардов (kind: post_time, post_dsq).
    Штрафы, выданные командами во время гонки, сервер уже учёл в результатах —
    здесь их повторно не считаем.
    Сортировка: больше кругов — выше, при равенстве меньше время с учётом штрафа.
    Дисквалифицированные уходят в конец.
    """
    sec, dsq = {}, set()
    for d in decisions:
        if d.get("kind") == "post_time":
            sec[d["num"]] = sec.get(d["num"], 0) + int(d.get("value") or 0)
        elif d.get("kind") == "post_dsq":
            dsq.add(d["num"])

    base_pos = {c["num"]: i + 1 for i, c in enumerate(cars)}
    big = 10 ** 13

    def key(c):
        total = c["total"] if c["total"] else big
        return (-c["laps"], total + sec.get(c["num"], 0) * 1000)

    ok = sorted([c for c in cars if c["num"] not in dsq], key=key)
    bad = [c for c in cars if c["num"] in dsq]
    out = []
    for i, c in enumerate(ok + bad):
        is_dsq = c["num"] in dsq
        out.append({
            "row": c,
            "pos": None if is_dsq else i + 1,
            "delta": 0 if is_dsq else base_pos[c["num"]] - (i + 1),
            "penalty_s": sec.get(c["num"], 0),
            "total_final": (c["total"] + sec.get(c["num"], 0) * 1000) if c["total"] else None,
            "dsq": is_dsq,
        })
    return out


def classification_text(rows) -> str:
    lines = []
    for r in rows:
        c = r["row"]
        pos = "DSQ" if r["dsq"] else "P%d" % r["pos"]
        tail = ""
        if r["penalty_s"]:
            tail = "  (+%d сек)" % r["penalty_s"]
        lines.append("%s  #%s  %s  %s%s" % (pos, c["num"], c["name"], fmt_total(r["total_final"]), tail))
    return "\n".join(lines)


def classification_rows_csv(rows) -> list:
    out = [["Позиция", "Номер", "Пилот", "Круги", "Время", "Штраф, сек", "Дисквалификация"]]
    for r in rows:
        c = r["row"]
        out.append([
            "" if r["dsq"] else r["pos"], c["num"], c["name"], c["laps"],
            fmt_total(r["total_final"]), r["penalty_s"], "да" if r["dsq"] else "",
        ])
    return out
