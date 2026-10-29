"""Критерии приёмки: пороги метрик из TOML-файла.

    [acceptance]
    ttff_max_s = 60
    rtk_fixed_ratio_min = 0.95
    cep95_max_m = 0.05

Суффикс задаёт направление проверки: ``_max`` — значение не больше порога,
``_min`` — не меньше. Неизвестный ключ — ошибка: опечатка в критерии не
должна молча превращать проверку в «всегда зелёную».
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .pipeline import AnalysisResult

Getter = Callable[[AnalysisResult], float | None]


@dataclass(frozen=True)
class CriterionSpec:
    title: str
    unit: str
    getter: Getter


CRITERIA: dict[str, CriterionSpec] = {
    "ttff": CriterionSpec("Время до первого решения (TTFF)", "с", lambda r: r.metrics.ttff_s),
    "time_to_rtk_fixed": CriterionSpec("Время до RTK fixed", "с", lambda r: r.metrics.time_to_rtk_fixed_s),
    "availability": CriterionSpec("Доступность решения", "", lambda r: r.metrics.availability),
    "rtk_fixed_ratio": CriterionSpec("Доля RTK fixed после фиксации", "", lambda r: r.metrics.rtk_fixed_ratio),
    "fix_downgrades": CriterionSpec("Потери RTK fixed", "шт.", lambda r: r.metrics.fix_downgrades),
    "max_gap": CriterionSpec("Максимальный разрыв потока", "с", lambda r: r.metrics.max_gap_s),
    "position_jumps": CriterionSpec("Скачки координат", "шт.", lambda r: r.metrics.position_jumps),
    "cep50": CriterionSpec("Горизонтальная ошибка CEP50", "м", lambda r: r.metrics.cep50_m),
    "cep95": CriterionSpec("Горизонтальная ошибка CEP95", "м", lambda r: r.metrics.cep95_m),
    "pdop_median": CriterionSpec("Медиана PDOP", "", lambda r: r.metrics.pdop_median),
    "bad_sentence_ratio": CriterionSpec("Доля битых строк", "", lambda r: r.bad_sentence_ratio),
}


class CriteriaError(ValueError):
    pass


@dataclass(frozen=True)
class Limit:
    key: str            # как в файле: 'ttff_max_s'
    metric: str         # 'ttff'
    op: str             # '<=' или '>='
    value: float


@dataclass(frozen=True)
class CheckResult:
    limit: Limit
    title: str
    unit: str
    actual: float | None
    passed: bool

    @property
    def message(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        if self.actual is None:
            return f"{self.title}: метрика не получена (порог {self.limit.op} {self.limit.value}{unit})"
        verdict = "OK" if self.passed else "FAIL"
        return f"{self.title}: {self.actual:g}{unit} (порог {self.limit.op} {self.limit.value:g}{unit}) — {verdict}"


def parse_limit(key: str, value: object) -> Limit:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CriteriaError(f"{key}: порог должен быть числом, получено {value!r}")
    for suffix, op in (("_max", "<="), ("_min", ">=")):
        head, sep, _unit = key.partition(suffix)
        if sep and head in CRITERIA and (not _unit or _unit.startswith("_")):
            return Limit(key, head, op, float(value))
    known = ", ".join(f"{k}_max/{k}_min" for k in CRITERIA)
    raise CriteriaError(f"неизвестный критерий {key!r}. Доступны: {known}")


def load_criteria(path: Path) -> list[Limit]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    table = data.get("acceptance")
    if not isinstance(table, dict) or not table:
        raise CriteriaError(f"{path}: нет секции [acceptance] или она пустая")
    return [parse_limit(k, v) for k, v in table.items()]


def evaluate(result: AnalysisResult, limits: list[Limit]) -> list[CheckResult]:
    checks = []
    for limit in limits:
        spec = CRITERIA[limit.metric]
        actual = spec.getter(result)
        if actual is None:
            passed = False
        elif limit.op == "<=":
            passed = actual <= limit.value
        else:
            passed = actual >= limit.value
        checks.append(CheckResult(limit, spec.title, spec.unit, actual, passed))
    return checks
