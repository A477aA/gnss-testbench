"""Метрики качества навигационного решения по последовательности эпох."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from itertools import pairwise

from ..geo import enu_offset, horizontal_error, percentile
from ..nmea import FixQuality
from .epochs import Epoch


@dataclass(frozen=True)
class Reference:
    """Опорная точка с известными координатами (например, пункт ГГС)."""

    lat: float
    lon: float

    @classmethod
    def parse(cls, text: str) -> Reference:
        """'55.6948,37.36125' -> Reference."""
        try:
            lat_s, lon_s = text.split(",")
            return cls(float(lat_s), float(lon_s))
        except ValueError as exc:
            raise ValueError(f"опорная точка задаётся как 'lat,lon', получено {text!r}") from exc


@dataclass(frozen=True)
class Event:
    t_s: float          # от начала записи
    kind: str
    detail: str


@dataclass
class Metrics:
    epochs: int = 0
    duration_s: float = 0.0
    rate_hz: float | None = None
    ttff_s: float | None = None                 # время до первого решения
    time_to_rtk_fixed_s: float | None = None    # время до RTK fixed
    availability: float = 0.0                   # доля ожидаемых эпох с решением
    rtk_fixed_ratio: float | None = None        # доля RTK fixed после первого fixed
    fix_downgrades: int = 0                     # потери RTK fixed
    gaps: list[tuple[float, float]] = field(default_factory=list)  # (начало, длительность)
    max_gap_s: float = 0.0
    position_jumps: int = 0
    cep50_m: float | None = None
    cep95_m: float | None = None
    max_error_m: float | None = None
    mean_offset_enu_m: tuple[float, float] | None = None  # систематический сдвиг
    pdop_median: float | None = None
    quality_counts: dict[str, int] = field(default_factory=dict)
    sats_in_view_max: dict[str, int] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)


def _expected_epochs(span_s: float, rate_hz: float) -> int:
    return round(span_s * rate_hz) + 1


def compute_metrics(
    epochs: list[Epoch],
    reference: Reference | None = None,
    *,
    jump_threshold_m: float = 0.5,
) -> Metrics:
    m = Metrics(epochs=len(epochs))
    if not epochs:
        return m

    gga = [e.gga for e in epochs if e.gga is not None]
    t0 = epochs[0].t
    rel = [e.t - t0 for e in epochs]
    m.duration_s = rel[-1]

    # Темп выдачи: медиана интервалов устойчива к разрывам
    intervals = [b - a for a, b in pairwise(rel) if b > a]
    if intervals:
        m.rate_hz = round(1 / statistics.median(intervals), 3)

    for g in gga:
        m.quality_counts[g.quality.name] = m.quality_counts.get(g.quality.name, 0) + 1
    for e in epochs:
        for system, n in e.sats_in_view.items():
            m.sats_in_view_max[system] = max(n, m.sats_in_view_max.get(system, 0))

    # Время до решения
    first_fix = next((i for i, g in enumerate(gga) if g.has_fix), None)
    if first_fix is not None:
        m.ttff_s = rel[first_fix]
        m.events.append(Event(rel[first_fix], "first_fix", gga[first_fix].quality.name))
    first_rtk = next((i for i, g in enumerate(gga) if g.quality is FixQuality.RTK_FIXED), None)
    if first_rtk is not None:
        m.time_to_rtk_fixed_s = rel[first_rtk]
        m.events.append(Event(rel[first_rtk], "rtk_fixed", "получено RTK fixed"))

    # Доступность и стабильность RTK с учётом пропущенных эпох
    if m.rate_hz:
        expected = _expected_epochs(m.duration_s, m.rate_hz)
        m.availability = round(sum(g.has_fix for g in gga) / expected, 4)
        if first_rtk is not None:
            expected_after = _expected_epochs(m.duration_s - rel[first_rtk], m.rate_hz)
            fixed = sum(g.quality is FixQuality.RTK_FIXED for g in gga[first_rtk:])
            m.rtk_fixed_ratio = round(fixed / expected_after, 4)

        # Разрывы потока: интервал заметно больше штатного
        nominal = 1 / m.rate_hz
        for a, b in pairwise(rel):
            if b - a > 1.5 * nominal:
                m.gaps.append((round(a, 3), round(b - a, 3)))
                m.events.append(Event(a, "gap", f"нет данных {b - a:.2f} с"))
        m.max_gap_s = max((d for _, d in m.gaps), default=nominal)

    # Потери RTK fixed
    for i in range(1, len(gga)):
        prev, cur = gga[i - 1].quality, gga[i].quality
        if prev is FixQuality.RTK_FIXED and cur is not FixQuality.RTK_FIXED:
            m.fix_downgrades += 1
            m.events.append(Event(rel[i], "downgrade", f"RTK_FIXED -> {cur.name}"))

    # Скачки координат между соседними RTK fixed эпохами
    fixed_pts = [(rel[i], g.lat, g.lon) for i, g in enumerate(gga)
                 if g.quality is FixQuality.RTK_FIXED and g.lat is not None and g.lon is not None]
    for (_, lat_a, lon_a), (tb, lat_b, lon_b) in pairwise(fixed_pts):
        jump = horizontal_error(lat_b, lon_b, lat_a, lon_a)
        if jump > jump_threshold_m:
            m.position_jumps += 1
            m.events.append(Event(tb, "jump", f"скачок {jump:.2f} м"))

    # Точность относительно опорной точки — только RTK fixed
    if reference is not None and fixed_pts:
        offsets = [enu_offset(lat, lon, reference.lat, reference.lon) for _, lat, lon in fixed_pts]
        errors = [(e**2 + n**2) ** 0.5 for e, n in offsets]
        m.cep50_m = round(percentile(errors, 50), 4)
        m.cep95_m = round(percentile(errors, 95), 4)
        m.max_error_m = round(max(errors), 4)
        m.mean_offset_enu_m = (
            round(statistics.fmean(e for e, _ in offsets), 4),
            round(statistics.fmean(n for _, n in offsets), 4),
        )

    pdops = [p for e in epochs if (p := e.pdop) is not None]
    if pdops:
        m.pdop_median = statistics.median(pdops)

    m.events.sort(key=lambda ev: ev.t_s)
    return m
