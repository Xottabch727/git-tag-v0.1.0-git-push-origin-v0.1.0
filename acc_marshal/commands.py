"""Виды решений стюардов, команды для чата сервера и шаблоны объявлений."""
import string

# Шаблоны команд. {num} — номер машины.
# ВАЖНО: названия команд нужно сверить с мануалом вашего сервера ACC
# (папка документов Assetto Corsa Competizione) и при необходимости поправить
# в файле config.json (раздел "commands") или прямо здесь.
DEFAULT_COMMANDS = {
    "tp5": "/tp5 {num}",
    "tp15": "/tp15 {num}",
    "dt": "/dt {num}",
    "dq": "/dq {num}",
    "clear": "/clear {num}",
    "clear_all": "/clear_all",
}

# Виды решений. cmd — ключ шаблона команды (если решение выдаётся командой в игре).
# value — подпись числового значения. hint — что произойдёт, если команды нет.
KINDS = [
    {"key": "tp5", "label": "+5 сек (в гонке)", "short": "+5 сек", "cmd": "tp5"},
    {"key": "tp15", "label": "+15 сек (в гонке)", "short": "+15 сек", "cmd": "tp15"},
    {"key": "dt", "label": "Проезд по пит-лейну (в гонке)", "short": "Проезд по пит-лейну", "cmd": "dt"},
    {"key": "dq", "label": "Дисквалификация (в гонке)", "short": "Дисквалификация", "cmd": "dq"},
    {"key": "post_time", "label": "Секунды к итогам гонки", "short": "+{value} сек к итогам",
     "value": "сек", "default": 10, "hint": "Команды нет: штраф попадёт во вкладку «Итоги гонки»."},
    {"key": "post_dsq", "label": "Дисквалификация по итогам", "short": "Дисквалификация по итогам",
     "hint": "Команды нет: пилот уйдёт в конец итогов гонки."},
    {"key": "grid", "label": "Откат на решётке (мест)", "short": "−{value} мест на решётке",
     "value": "мест", "default": 3, "hint": "Команды нет: штраф попадёт во вкладку «Решётка»."},
    {"key": "pit", "label": "Старт с пит-лейна", "short": "Старт с пит-лейна",
     "hint": "Команды нет: пилот уйдёт в конец решётки."},
    {"key": "warn", "label": "Предупреждение", "short": "Предупреждение",
     "hint": "Команды нет: запись остаётся только в журнале."},
]
KIND_BY_KEY = {k["key"]: k for k in KINDS}
KIND_BY_LABEL = {k["label"]: k for k in KINDS}


def build_command(kind_key, num, templates=None):
    """Команда для чата сервера или None, если для этого решения команды нет."""
    spec = KIND_BY_KEY.get(kind_key)
    if not spec or not spec.get("cmd") or num is None:
        return None
    templates = templates or DEFAULT_COMMANDS
    tpl = templates.get(spec["cmd"]) or DEFAULT_COMMANDS.get(spec["cmd"])
    return tpl.format(num=num) if tpl else None


def undo_command(num, templates=None):
    templates = templates or DEFAULT_COMMANDS
    tpl = templates.get("clear") or DEFAULT_COMMANDS["clear"]
    return tpl.format(num=num)


def describe_decision(d) -> str:
    spec = KIND_BY_KEY.get(d.get("kind"))
    if not spec:
        return str(d.get("kind"))
    return spec["short"].format(value=d.get("value") or "")


# ---------------------------------------------------------- объявления --

DEFAULT_ANNOUNCEMENTS = [
    ("Виртуальный сейфти-кар (VSC)",
     "VSC! Виртуальный сейфти-кар. Сбросьте скорость, держите дистанцию, обгоны запрещены. {reason}"),
    ("VSC заканчивается",
     "VSC заканчивается. Гонка продолжается, будьте внимательны на рестарте."),
    ("Сейфти-кар (SC)",
     "SC! Сейфти-кар на трассе. Выстраиваемся в колонну, обгоны запрещены. {reason}"),
    ("Сейфти-кар уходит",
     "SC заходит в пит-лейн. Рестарт на следующем круге."),
    ("Красный флаг",
     "Красный флаг! Гонка остановлена. Сбросьте скорость и следуйте в пит-лейн без обгонов."),
    ("Жёлтый флаг",
     "Жёлтый флаг на трассе. {reason} Осторожно, обгоны запрещены."),
    ("Инцидент на рассмотрении",
     "Инцидент с участием #{num} взят на рассмотрение стюардами."),
    ("Нарушения нет",
     "Инцидент с участием #{num} рассмотрен: нарушения нет."),
    ("Предупреждение пилоту",
     "#{num} {name}: предупреждение. {reason}"),
    ("Штраф пилоту",
     "#{num} {name}: назначен штраф. {reason}"),
]


class _Safe(dict):
    def __missing__(self, key):
        return ""


def render(text, **ctx) -> str:
    """Подставляет {num}, {name}, {reason}; неизвестные поля становятся пустыми."""
    try:
        out = string.Formatter().vformat(text, (), _Safe(ctx))
    except (ValueError, IndexError):
        out = text
    return " ".join(out.split())


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def translit(text: str) -> str:
    """Кириллица → латиница (на случай, если чат игры не показывает русские буквы)."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            t = _TRANSLIT[low]
            out.append(t.capitalize() if ch != low else t)
        else:
            out.append(ch)
    return "".join(out)
