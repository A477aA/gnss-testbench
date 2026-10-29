"""Сборка эпох: все сообщения, относящиеся к одному моменту измерения.

Время есть только в GGA и RMC. GSA и GSV времени не содержат, поэтому
привязываются к последней эпохе — так их выдаёт любой приёмник: пачка
сообщений на каждую эпоху. Сообщения до первой эпохи отбрасываются.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import time

from ..nmea import CONSTELLATIONS, GGA, GSA, GSV, RMC, Sentence


def seconds_of_day(t: time) -> float:
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond / 1e6


@dataclass
class Epoch:
    t: float                                   # секунды от начала суток UTC
    gga: GGA | None = None
    rmc: RMC | None = None
    gsa: list[GSA] = field(default_factory=list)
    sats_in_view: dict[str, int] = field(default_factory=dict)   # система -> число

    @property
    def pdop(self) -> float | None:
        values = [g.pdop for g in self.gsa if g.pdop is not None]
        return min(values) if values else None


def build_epochs(sentences: Iterable[Sentence]) -> list[Epoch]:
    epochs: dict[float, Epoch] = {}
    current: Epoch | None = None
    for s in sentences:
        if isinstance(s, (GGA, RMC)):
            if s.utc is None:
                continue
            t = seconds_of_day(s.utc)
            if current is not None and t < current.t - 43200:
                t += 86400                     # переход через полночь UTC
            current = epochs.setdefault(t, Epoch(t))
            if isinstance(s, GGA):
                current.gga = s
            else:
                current.rmc = s
        elif current is None:
            continue
        elif isinstance(s, GSA):
            current.gsa.append(s)
        elif isinstance(s, GSV) and s.msg_num == 1:
            current.sats_in_view[CONSTELLATIONS.get(s.talker, s.talker)] = s.sats_in_view
    return sorted((e for e in epochs.values() if e.gga is not None), key=lambda e: e.t)
