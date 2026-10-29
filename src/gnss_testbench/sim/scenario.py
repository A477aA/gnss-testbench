"""Сценарий работы виртуального приёмника (TOML).

Сценарий — это последовательность фаз (холодный старт, автономное решение,
RTK float, RTK fixed...) и список внесённых дефектов: пропадание данных,
битые контрольные суммы, мусор в порту, скачки координат. Сценарий
детерминирован: одинаковый seed — побайтно одинаковый поток.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..nmea import FixQuality


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Phase:
    duration_s: float
    quality: FixQuality
    sats: int = 0
    hdop: float = 99.0
    sigma_m: float = 0.0            # СКО горизонтальной ошибки
    bias_east_m: float = 0.0        # систематический сдвиг (например, многолучёвость)
    bias_north_m: float = 0.0


@dataclass(frozen=True)
class Window:
    start_s: float
    duration_s: float

    def contains(self, t: float) -> bool:
        return self.start_s <= t < self.start_s + self.duration_s


@dataclass(frozen=True)
class Jump:
    """Временный сдвиг решения — как при ложной фиксации неоднозначности."""

    at_s: float
    east_m: float
    north_m: float = 0.0
    duration_s: float = 1.0

    def active(self, t: float) -> bool:
        return self.at_s <= t < self.at_s + self.duration_s


@dataclass(frozen=True)
class Faults:
    dropouts: tuple[Window, ...] = ()          # приёмник молчит
    corrupt_checksum_at_s: tuple[float, ...] = ()
    truncate_at_s: tuple[float, ...] = ()      # строка обрывается на середине
    jumps: tuple[Jump, ...] = ()
    garbage_probability: float = 0.0           # вероятность мусора между эпохами
    corrupt_probability: float = 0.0           # вероятность искажения байта в строке


@dataclass(frozen=True)
class Scenario:
    name: str
    ref_lat: float
    ref_lon: float
    ref_alt_m: float
    phases: tuple[Phase, ...]
    rate_hz: float = 1.0
    seed: int = 0
    start_utc_s: float = 9 * 3600
    date: str = "291026"
    faults: Faults = field(default_factory=Faults)

    @property
    def duration_s(self) -> float:
        return sum(p.duration_s for p in self.phases)

    def phase_at(self, t: float) -> Phase:
        elapsed = 0.0
        for phase in self.phases:
            elapsed += phase.duration_s
            if t < elapsed:
                return phase
        return self.phases[-1]


def _quality(value: Any) -> FixQuality:
    try:
        return FixQuality[str(value).upper()]
    except KeyError:
        names = ", ".join(q.name for q in FixQuality)
        raise ScenarioError(f"неизвестное качество решения {value!r}; доступны: {names}") from None


def _hms(value: str) -> float:
    try:
        h, m, s = (float(x) for x in value.split(":"))
    except ValueError:
        raise ScenarioError(f"время задаётся как 'hh:mm:ss', получено {value!r}") from None
    return h * 3600 + m * 60 + s


def from_dict(data: dict[str, Any]) -> Scenario:
    try:
        ref = data["reference"]
        phases = tuple(
            Phase(
                duration_s=float(p["duration_s"]),
                quality=_quality(p["quality"]),
                sats=int(p.get("sats", 0)),
                hdop=float(p.get("hdop", 99.0)),
                sigma_m=float(p.get("sigma_m", 0.0)),
                bias_east_m=float(p.get("bias_east_m", 0.0)),
                bias_north_m=float(p.get("bias_north_m", 0.0)),
            )
            for p in data["phase"]
        )
        f = data.get("faults", {})
        faults = Faults(
            dropouts=tuple(Window(float(w["start_s"]), float(w["duration_s"])) for w in f.get("dropouts", [])),
            corrupt_checksum_at_s=tuple(float(x) for x in f.get("corrupt_checksum_at_s", [])),
            truncate_at_s=tuple(float(x) for x in f.get("truncate_at_s", [])),
            jumps=tuple(Jump(float(j["at_s"]), float(j["east_m"]), float(j.get("north_m", 0)),
                             float(j.get("duration_s", 1.0)))
                        for j in f.get("jumps", [])),
            garbage_probability=float(f.get("garbage_probability", 0.0)),
            corrupt_probability=float(f.get("corrupt_probability", 0.0)),
        )
        scenario = Scenario(
            name=str(data.get("name", "без названия")),
            ref_lat=float(ref["lat"]),
            ref_lon=float(ref["lon"]),
            ref_alt_m=float(ref.get("alt_m", 0.0)),
            phases=phases,
            rate_hz=float(data.get("rate_hz", 1.0)),
            seed=int(data.get("seed", 0)),
            start_utc_s=_hms(data.get("start_utc", "09:00:00")),
            faults=faults,
        )
    except KeyError as exc:
        raise ScenarioError(f"в сценарии не хватает поля {exc}") from None
    _validate(scenario)
    return scenario


def _validate(s: Scenario) -> None:
    if not s.phases:
        raise ScenarioError("нужна хотя бы одна фаза [[phase]]")
    if not 0 < s.rate_hz <= 100:
        raise ScenarioError(f"rate_hz должен быть в диапазоне (0, 100], получено {s.rate_hz}")
    if not -90 <= s.ref_lat <= 90 or not -180 <= s.ref_lon <= 180:
        raise ScenarioError("опорная точка вне допустимых координат")
    for p in s.phases:
        if p.duration_s <= 0:
            raise ScenarioError("длительность фазы должна быть положительной")
        if p.sigma_m < 0:
            raise ScenarioError("sigma_m не может быть отрицательной")
    for prob in (s.faults.garbage_probability, s.faults.corrupt_probability):
        if not 0 <= prob <= 1:
            raise ScenarioError("вероятность должна быть в диапазоне 0..1")


def load_scenario(path: Path) -> Scenario:
    with path.open("rb") as fh:
        return from_dict(tomllib.load(fh))
