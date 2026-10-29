"""Разбор и формирование строк NMEA 0183.

Парсер строгий: любое отклонение от формата — ``NmeaError`` с понятным
сообщением, а не молчаливое ``None``. Для тестирования прошивок это важно:
если приёмник выдал кривую строку, мы хотим об этом узнать.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, time

from .sentences import (
    GGA,
    GSA,
    GSV,
    RMC,
    VTG,
    FixMode,
    FixQuality,
    SatInView,
    Sentence,
)


class NmeaError(ValueError):
    """Строку нельзя разобрать."""


class FramingError(NmeaError):
    """Нарушено обрамление: нет '$', '*' или контрольной суммы."""


class ChecksumError(NmeaError):
    """Контрольная сумма не совпала — данные искажены при передаче."""


class FieldError(NmeaError):
    """Обрамление в порядке, но содержимое полей некорректно."""


# --- Обрамление и контрольная сумма ------------------------------------------

def checksum(body: str) -> str:
    """XOR всех символов между '$' и '*' в виде двух hex-цифр."""
    value = 0
    for ch in body:
        value ^= ord(ch)
    return f"{value:02X}"


def build_sentence(body: str) -> str:
    """'GPGGA,...' -> '$GPGGA,...*47'."""
    return f"${body}*{checksum(body)}"


def split_sentence(line: str) -> list[str]:
    """Проверяет обрамление и контрольную сумму, возвращает поля."""
    line = line.strip("\r\n ")
    if not line.startswith("$"):
        raise FramingError("строка должна начинаться с '$'")
    star = line.rfind("*")
    if star == -1:
        raise FramingError("нет контрольной суммы ('*XX')")
    body, received = line[1:star], line[star + 1:]
    if len(received) != 2:
        raise FramingError(f"контрольная сумма должна быть из 2 символов, получено {received!r}")
    expected = checksum(body)
    if received.upper() != expected:
        raise ChecksumError(f"контрольная сумма не совпала: получено {received}, ожидалось {expected}")
    fields = body.split(",")
    address = fields[0]
    if len(address) != 5 or not address.isalnum() or not address.isupper():
        raise FramingError(f"некорректный адрес сообщения: {address!r}")
    return fields


# --- Поля ----------------------------------------------------------------------

def _int(value: str, name: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise FieldError(f"{name}: ожидалось целое, получено {value!r}") from exc


def _float(value: str, name: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise FieldError(f"{name}: ожидалось число, получено {value!r}") from exc


def parse_coord(value: str, hemisphere: str, *, is_lat: bool) -> float | None:
    """'5541.68800', 'N' -> 55.69480. Пустое поле — нет координаты."""
    if not value and not hemisphere:
        return None
    deg_digits, limit = (2, 90) if is_lat else (3, 180)
    point = value.find(".")
    if point != deg_digits + 2 or not value.replace(".", "", 1).isdigit():
        kind = "широта" if is_lat else "долгота"
        raise FieldError(f"{kind}: ожидался формат {'d' * deg_digits}mm.mmmm, получено {value!r}")
    degrees = int(value[:deg_digits])
    minutes = float(value[deg_digits:])
    if minutes >= 60:
        raise FieldError(f"минут не может быть {minutes}")
    result = degrees + minutes / 60
    if result > limit:
        raise FieldError(f"координата {result:.6f} вне диапазона ±{limit}")
    valid = ("N", "S") if is_lat else ("E", "W")
    if hemisphere not in valid:
        raise FieldError(f"полушарие должно быть одним из {valid}, получено {hemisphere!r}")
    return -result if hemisphere in ("S", "W") else result


def format_coord(value: float, *, is_lat: bool, decimals: int = 7) -> tuple[str, str]:
    """55.6948 -> ('5541.6880000', 'N'). Обратное к parse_coord."""
    hemisphere = ("N" if value >= 0 else "S") if is_lat else ("E" if value >= 0 else "W")
    value = abs(value)
    degrees = int(value)
    minutes = round((value - degrees) * 60, decimals)
    if minutes >= 60:                     # 59.99999999 округлилось до 60
        degrees, minutes = degrees + 1, 0.0
    width = 2 if is_lat else 3
    return f"{degrees:0{width}d}{minutes:0{decimals + 3}.{decimals}f}", hemisphere


def parse_time(value: str) -> time | None:
    """'093015.25' -> 09:30:15.250000."""
    if not value:
        return None
    if len(value) < 6 or not value[:6].isdigit():
        raise FieldError(f"время: ожидался формат hhmmss.ss, получено {value!r}")
    try:
        seconds = float(value[4:])
        whole = int(seconds)
        return time(int(value[:2]), int(value[2:4]), whole, round((seconds - whole) * 1e6))
    except ValueError as exc:
        raise FieldError(f"время вне диапазона: {value!r}") from exc


def format_time(seconds_of_day: float) -> str:
    """33015.25 -> '091015.25'."""
    seconds_of_day %= 86400
    hh, rem = divmod(seconds_of_day, 3600)
    mm, ss = divmod(rem, 60)
    return f"{int(hh):02d}{int(mm):02d}{ss:05.2f}"


#: В RMC год двузначный. GPS-время отсчитывается с 1980 года, поэтому
#: yy >= 80 — это 19yy, иначе 20yy (так же делают gpsd и pynmea2).
CENTURY_PIVOT = 80


def parse_date(value: str) -> date | None:
    """'291026' -> 2026-10-29, '230394' -> 1994-03-23."""
    if not value:
        return None
    if len(value) != 6 or not value.isdigit():
        raise FieldError(f"дата: ожидался формат ddmmyy, получено {value!r}")
    yy = int(value[4:])
    year = 1900 + yy if yy >= CENTURY_PIVOT else 2000 + yy
    try:
        return date(year, int(value[2:4]), int(value[:2]))
    except ValueError as exc:
        raise FieldError(f"несуществующая дата: {value!r}") from exc


def _require(fields: list[str], count: int) -> None:
    if len(fields) < count:
        raise FieldError(f"{fields[0]}: ожидалось минимум {count} полей, получено {len(fields)}")


# --- Сообщения ----------------------------------------------------------------

def parse_gga(f: list[str]) -> GGA:
    _require(f, 15)
    quality_raw = _int(f[6], "качество решения")
    try:
        quality = FixQuality(quality_raw or 0)
    except ValueError as exc:
        raise FieldError(f"неизвестное качество решения: {f[6]!r}") from exc
    lat = parse_coord(f[2], f[3], is_lat=True)
    lon = parse_coord(f[4], f[5], is_lat=False)
    if quality is not FixQuality.NO_FIX and (lat is None or lon is None):
        raise FieldError(f"качество решения {quality.name}, но координаты пустые")
    return GGA(
        talker=f[0][:2],
        utc=parse_time(f[1]),
        lat=lat,
        lon=lon,
        quality=quality,
        satellites=_int(f[7], "число спутников") or 0,
        hdop=_float(f[8], "HDOP"),
        altitude_m=_float(f[9], "высота"),
        geoid_sep_m=_float(f[11], "превышение геоида"),
        correction_age_s=_float(f[13], "возраст поправок"),
        station_id=f[14] or None,
    )


def parse_rmc(f: list[str]) -> RMC:
    _require(f, 12)
    if f[2] not in ("A", "V"):
        raise FieldError(f"статус RMC должен быть 'A' или 'V', получено {f[2]!r}")
    return RMC(
        talker=f[0][:2],
        utc=parse_time(f[1]),
        valid=f[2] == "A",
        lat=parse_coord(f[3], f[4], is_lat=True),
        lon=parse_coord(f[5], f[6], is_lat=False),
        speed_knots=_float(f[7], "скорость"),
        course_deg=_float(f[8], "курс"),
        date=parse_date(f[9]),
    )


def parse_gsa(f: list[str]) -> GSA:
    _require(f, 18)
    if f[1] not in ("A", "M"):
        raise FieldError(f"режим GSA должен быть 'A' или 'M', получено {f[1]!r}")
    mode_raw = _int(f[2], "тип решения")
    try:
        fix_mode = FixMode(1 if mode_raw is None else mode_raw)
    except ValueError as exc:
        raise FieldError(f"неизвестный тип решения: {f[2]!r}") from exc
    prns = tuple(p for p in (_int(v, "PRN") for v in f[3:15]) if p is not None)
    return GSA(
        talker=f[0][:2],
        auto_mode=f[1] == "A",
        fix_mode=fix_mode,
        prns=prns,
        pdop=_float(f[15], "PDOP"),
        hdop=_float(f[16], "HDOP"),
        vdop=_float(f[17], "VDOP"),
        system_id=_int(f[18], "system ID") if len(f) > 18 else None,
    )


def parse_gsv(f: list[str]) -> GSV:
    _require(f, 4)
    total, num, in_view = (_int(f[i], n) for i, n in ((1, "всего"), (2, "номер"), (3, "в зоне")))
    if total is None or num is None or in_view is None:
        raise FieldError("GSV: пустые служебные поля")
    if not 1 <= num <= total:
        raise FieldError(f"GSV: номер части {num} вне диапазона 1..{total}")
    sat_fields = f[4:]
    if len(sat_fields) % 4 == 1:          # NMEA 4.10: в конце signal ID
        sat_fields = sat_fields[:-1]
    if len(sat_fields) % 4:
        raise FieldError(f"GSV: блоки спутников должны быть по 4 поля, получено {len(sat_fields)}")
    sats = []
    for i in range(0, len(sat_fields), 4):
        prn = _int(sat_fields[i], "PRN")
        if prn is None:
            continue
        elev = _int(sat_fields[i + 1], "угол места")
        if elev is not None and not -90 <= elev <= 90:
            raise FieldError(f"угол места {elev} вне диапазона")
        az = _int(sat_fields[i + 2], "азимут")
        if az is not None and not 0 <= az <= 359:
            raise FieldError(f"азимут {az} вне диапазона")
        snr = _int(sat_fields[i + 3], "SNR")
        if snr is not None and not 0 <= snr <= 99:
            raise FieldError(f"SNR {snr} вне диапазона")
        sats.append(SatInView(prn, elev, az, snr))
    return GSV(f[0][:2], total, num, in_view, tuple(sats))


def parse_vtg(f: list[str]) -> VTG:
    _require(f, 9)
    return VTG(
        talker=f[0][:2],
        course_true_deg=_float(f[1], "курс"),
        speed_knots=_float(f[5], "скорость, узлы"),
        speed_kmh=_float(f[7], "скорость, км/ч"),
    )


PARSERS: dict[str, Callable[[list[str]], Sentence]] = {
    "GGA": parse_gga,
    "RMC": parse_rmc,
    "GSA": parse_gsa,
    "GSV": parse_gsv,
    "VTG": parse_vtg,
}


def parse(line: str) -> Sentence | None:
    """Разбирает строку. Неподдерживаемый тип -> None, ошибка -> NmeaError."""
    fields = split_sentence(line)
    handler = PARSERS.get(fields[0][2:])
    return handler(fields) if handler else None
