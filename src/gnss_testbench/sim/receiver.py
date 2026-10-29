"""Виртуальный GNSS-приёмник: превращает сценарий в поток байт NMEA.

На каждую эпоху выдаётся пачка GGA, RMC, GSA (GPS и ГЛОНАСС), GSV — как у
типичного многосистемного приёмника. Дефекты из сценария вносятся на уровне
байт, поэтому декодер и анализатор проверяются на тех же данных, что пришли
бы с реального порта.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass

from ..geo import offset_position
from ..nmea import FixQuality, build_sentence, format_coord, format_time
from .scenario import Phase, Scenario

CRLF = b"\r\n"


@dataclass(frozen=True)
class Satellite:
    system: str       # talker ID: GP / GL
    prn: int
    elevation: int
    azimuth: int


@dataclass(frozen=True)
class EpochOutput:
    t_s: float        # время от начала сценария
    data: bytes


class VirtualReceiver:
    def __init__(self, scenario: Scenario) -> None:
        self.s = scenario
        self.rng = random.Random(scenario.seed)
        # Созвездие фиксируем на весь сценарий: за минуты геометрия почти не меняется
        sky = random.Random(scenario.seed + 1)
        self.sky = {
            "GP": [Satellite("GP", prn, sky.randint(5, 85), sky.randint(0, 359))
                   for prn in sorted(sky.sample(range(1, 33), 14))],
            "GL": [Satellite("GL", prn, sky.randint(5, 85), sky.randint(0, 359))
                   for prn in sorted(sky.sample(range(65, 89), 12))],
        }

    # --- Модель решения -------------------------------------------------------

    def _position(self, t: float, phase: Phase) -> tuple[float, float, float]:
        east = phase.bias_east_m + self.rng.gauss(0, phase.sigma_m)
        north = phase.bias_north_m + self.rng.gauss(0, phase.sigma_m)
        up = self.rng.gauss(0, phase.sigma_m * 1.5)
        for jump in self.s.faults.jumps:
            if jump.active(t):
                east += jump.east_m
                north += jump.north_m
        lat, lon = offset_position(self.s.ref_lat, self.s.ref_lon, east, north)
        return lat, lon, self.s.ref_alt_m + up

    def _split_sats(self, total: int) -> dict[str, list[Satellite]]:
        gps = min(math.ceil(total * 0.55), len(self.sky["GP"]))
        glo = min(total - gps, len(self.sky["GL"]))
        # В решение идут спутники с наибольшим углом места
        best = {k: sorted(v, key=lambda s: -s.elevation) for k, v in self.sky.items()}
        return {"GP": best["GP"][:gps], "GL": best["GL"][:glo]}

    # --- Сообщения ------------------------------------------------------------

    def _epoch_sentences(self, t: float, phase: Phase) -> list[str]:
        utc = format_time(self.s.start_utc_s + t)
        fix = phase.quality is not FixQuality.NO_FIX
        rtk = phase.quality in (FixQuality.RTK_FIXED, FixQuality.RTK_FLOAT)
        used = self._split_sats(phase.sats)
        n_used = sum(len(v) for v in used.values()) if fix else 0

        if fix:
            lat, lon, alt = self._position(t, phase)
            la, ns = format_coord(lat, is_lat=True)
            lo, ew = format_coord(lon, is_lat=False)
            hdop = max(0.5, phase.hdop + self.rng.uniform(-0.1, 0.1))
            age, station = ("1.0", "0001") if rtk else ("", "")
            gga = (f"GNGGA,{utc},{la},{ns},{lo},{ew},{int(phase.quality)},{n_used:02d},"
                   f"{hdop:.1f},{alt:.3f},M,14.200,M,{age},{station}")
            rmc = f"GNRMC,{utc},A,{la},{ns},{lo},{ew},0.01,,{self.s.date},,,D"
        else:
            hdop = 99.9
            gga = f"GNGGA,{utc},,,,,0,{n_used:02d},,,M,,M,,"
            rmc = f"GNRMC,{utc},V,,,,,,,{self.s.date},,,N"

        out = [gga, rmc]
        for system_id, sats in enumerate(used.values(), start=1):   # 1 — GPS, 2 — ГЛОНАСС
            prns = [f"{s.prn:02d}" for s in sats] if fix else []
            prns += [""] * (12 - len(prns))
            mode = "3" if fix else "1"
            dops = f"{hdop * 1.3:.1f},{hdop:.1f},{hdop * 1.1:.1f}" if fix else ",,"
            out.append(f"GNGSA,A,{mode},{','.join(prns[:12])},{dops},{system_id}")
        for talker, sats in self.sky.items():
            visible = sats[: max(len(used[talker]) + 2, 4)] if phase.sats else sats[:2]
            out.extend(self._gsv(talker, visible))
        return [build_sentence(body) for body in out]

    def _gsv(self, talker: str, sats: list[Satellite]) -> list[str]:
        chunks = [sats[i:i + 4] for i in range(0, len(sats), 4)] or [[]]
        bodies = []
        for num, chunk in enumerate(chunks, start=1):
            fields = [f"{talker}GSV", str(len(chunks)), str(num), f"{len(sats):02d}"]
            for s in chunk:
                snr = max(0, min(99, int(20 + s.elevation / 3 + self.rng.gauss(0, 2))))
                fields += [f"{s.prn:02d}", f"{s.elevation:02d}", f"{s.azimuth:03d}", f"{snr:02d}"]
            bodies.append(",".join(fields))
        return bodies

    # --- Дефекты --------------------------------------------------------------

    @staticmethod
    def _at(t: float, moments: tuple[float, ...]) -> bool:
        return any(abs(t - m) < 1e-6 for m in moments)

    def _apply_faults(self, t: float, lines: list[str]) -> bytes:
        f = self.s.faults
        raw = [line.encode("ascii") for line in lines]
        if self._at(t, f.corrupt_checksum_at_s):
            good = raw[0][-2:].decode()
            bad = f"{(int(good, 16) + 1) % 256:02X}"
            raw[0] = raw[0][:-2] + bad.encode()
        for i, line in enumerate(raw):
            if f.corrupt_probability and self.rng.random() < f.corrupt_probability:
                pos = self.rng.randrange(1, len(line) - 3)
                damaged = bytearray(line)
                damaged[pos] = self.rng.choice(b"0123456789ABCDEF,.")
                if damaged[pos] == line[pos]:
                    damaged[pos] = ord("Z")
                raw[i] = bytes(damaged)
        data = b"".join(line + CRLF for line in raw)
        if self._at(t, f.truncate_at_s):
            cut = len(raw[0]) // 2
            data = raw[0][:cut] + data[len(raw[0]) + 2:]      # GGA без конца и без CRLF
        if f.garbage_probability and self.rng.random() < f.garbage_probability:
            noise = bytes(self.rng.choice([b for b in range(256) if b not in b"$\r\n"])
                          for _ in range(self.rng.randint(5, 30)))
            data = noise + data
        return data

    # --- Выдача -----------------------------------------------------------------

    def epochs(self) -> Iterator[EpochOutput]:
        count = round(self.s.duration_s * self.s.rate_hz)
        for i in range(count):
            t = round(i / self.s.rate_hz, 6)
            phase = self.s.phase_at(t)
            lines = self._epoch_sentences(t, phase)    # генерируем всегда — RNG не сбивается
            if any(w.contains(t) for w in self.s.faults.dropouts):
                continue
            yield EpochOutput(t, self._apply_faults(t, lines))

    def to_bytes(self) -> bytes:
        return b"".join(e.data for e in self.epochs())
