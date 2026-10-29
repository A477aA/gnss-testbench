"""Геометрия на малых расстояниях: смещения в метрах относительно опорной точки.

Для оценки точности RTK (сантиметры–метры) достаточно локальной касательной
плоскости: ошибка аппроксимации на таких масштабах пренебрежимо мала.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

EARTH_RADIUS_M = 6_371_008.8


def enu_offset(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """Смещение точки относительно опорной: (восток, север) в метрах."""
    north = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    east = math.radians(lon - ref_lon) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    return east, north


def offset_position(ref_lat: float, ref_lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    """Обратное к enu_offset: точка, смещённая на (восток, север) метров."""
    lat = ref_lat + math.degrees(north_m / EARTH_RADIUS_M)
    lon = ref_lon + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(ref_lat))))
    return lat, lon


def horizontal_error(lat: float, lon: float, ref_lat: float, ref_lon: float) -> float:
    east, north = enu_offset(lat, lon, ref_lat, ref_lon)
    return math.hypot(east, north)


def percentile(values: Sequence[float], p: float) -> float:
    """Перцентиль с линейной интерполяцией (как numpy.percentile по умолчанию)."""
    if not values:
        raise ValueError("пустая выборка")
    if not 0 <= p <= 100:
        raise ValueError("p должен быть в диапазоне 0..100")
    data = sorted(values)
    k = (len(data) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)
