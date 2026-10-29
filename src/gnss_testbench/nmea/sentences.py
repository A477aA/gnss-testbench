"""Типизированные NMEA-сообщения."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import IntEnum


class FixQuality(IntEnum):
    """GGA, поле 6: качество решения."""

    NO_FIX = 0
    GPS = 1          # автономное решение, ~метры
    DGPS = 2         # дифференциальные поправки (SBAS/DGPS), ~дециметры–метр
    PPS = 3
    RTK_FIXED = 4    # RTK, неоднозначность фазы разрешена, ~сантиметры
    RTK_FLOAT = 5    # RTK, неоднозначность не разрешена, ~дециметры
    ESTIMATED = 6    # счисление (dead reckoning)
    MANUAL = 7
    SIMULATION = 8


class FixMode(IntEnum):
    """GSA, поле 2: размерность решения."""

    NO_FIX = 1
    FIX_2D = 2
    FIX_3D = 3


#: Идентификатор источника (talker ID) -> навигационная система.
CONSTELLATIONS: dict[str, str] = {
    "GP": "GPS",
    "GL": "GLONASS",
    "GA": "Galileo",
    "GB": "BeiDou",
    "BD": "BeiDou",
    "GQ": "QZSS",
    "GI": "NavIC",
    "GN": "Multi-GNSS",
}


@dataclass(frozen=True, slots=True)
class GGA:
    """Время, координаты и качество решения."""

    talker: str
    utc: time | None
    lat: float | None
    lon: float | None
    quality: FixQuality
    satellites: int
    hdop: float | None
    altitude_m: float | None
    geoid_sep_m: float | None
    correction_age_s: float | None
    station_id: str | None

    @property
    def has_fix(self) -> bool:
        return self.quality is not FixQuality.NO_FIX


@dataclass(frozen=True, slots=True)
class RMC:
    """Минимальный рекомендуемый набор: время, дата, координаты, скорость."""

    talker: str
    utc: time | None
    valid: bool
    lat: float | None
    lon: float | None
    speed_knots: float | None
    course_deg: float | None
    date: date | None


@dataclass(frozen=True, slots=True)
class GSA:
    """Спутники, участвующие в решении, и факторы DOP."""

    talker: str
    auto_mode: bool
    fix_mode: FixMode
    prns: tuple[int, ...]
    pdop: float | None
    hdop: float | None
    vdop: float | None
    system_id: int | None   # NMEA 4.10+: 1 GPS, 2 GLONASS, 3 Galileo, 4 BeiDou


@dataclass(frozen=True, slots=True)
class SatInView:
    prn: int
    elevation_deg: int | None
    azimuth_deg: int | None
    snr_dbhz: int | None


@dataclass(frozen=True, slots=True)
class GSV:
    """Спутники в зоне видимости (одна часть многострочного сообщения)."""

    talker: str
    total_msgs: int
    msg_num: int
    sats_in_view: int
    sats: tuple[SatInView, ...]


@dataclass(frozen=True, slots=True)
class VTG:
    """Курс и скорость над землёй."""

    talker: str
    course_true_deg: float | None
    speed_knots: float | None
    speed_kmh: float | None


Sentence = GGA | RMC | GSA | GSV | VTG
