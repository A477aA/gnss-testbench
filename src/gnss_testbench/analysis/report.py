"""Отчёты: Markdown для людей, JUnit XML для CI, JSON для машин."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import asdict
from typing import Any

from .criteria import CheckResult
from .pipeline import AnalysisResult


def _fmt(value: float | None, unit: str = "", digits: int = 3) -> str:
    if value is None:
        return "—"
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return f"{text} {unit}".strip()


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


def to_dict(result: AnalysisResult, checks: list[CheckResult] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "stream": {**asdict(result.stream), "bad_ratio": result.stream.bad_ratio},
        "field_errors": result.field_errors,
        "unsupported_sentences": result.unsupported,
        "bad_sentence_ratio": result.bad_sentence_ratio,
        "metrics": asdict(result.metrics),
        "errors": result.errors,
    }
    if checks is not None:
        data["acceptance"] = {
            "passed": all(c.passed for c in checks),
            "checks": [
                {"criterion": c.limit.key, "title": c.title, "actual": c.actual,
                 "op": c.limit.op, "limit": c.limit.value, "passed": c.passed}
                for c in checks
            ],
        }
    return data


def to_json(result: AnalysisResult, checks: list[CheckResult] | None = None) -> str:
    return json.dumps(to_dict(result, checks), ensure_ascii=False, indent=2)


def to_markdown(result: AnalysisResult, checks: list[CheckResult] | None = None,
                title: str = "Анализ лога GNSS-приёмника") -> str:
    m, s = result.metrics, result.stream
    lines = [f"# {title}", ""]

    if checks is not None:
        ok = all(c.passed for c in checks)
        failed = sum(not c.passed for c in checks)
        lines += [f"**Итог приёмки: {'ПРОЙДЕНА ✅' if ok else f'НЕ ПРОЙДЕНА ❌ ({failed} из {len(checks)})'}**", "",
                  "| Критерий | Факт | Порог | Результат |", "|---|---|---|---|"]
        for c in checks:
            lines.append(f"| {c.title} | {_fmt(c.actual, c.unit)} | {c.limit.op} {_fmt(c.limit.value, c.unit)} "
                         f"| {'✅' if c.passed else '❌'} |")
        lines.append("")

    lines += [
        "## Решение", "",
        "| Метрика | Значение |", "|---|---|",
        f"| Эпох | {m.epochs} за {_fmt(m.duration_s, 'с')} ({_fmt(m.rate_hz, 'Гц')}) |",
        f"| TTFF | {_fmt(m.ttff_s, 'с')} |",
        f"| Время до RTK fixed | {_fmt(m.time_to_rtk_fixed_s, 'с')} |",
        f"| Доступность решения | {_pct(m.availability)} |",
        f"| Доля RTK fixed после фиксации | {_pct(m.rtk_fixed_ratio)} |",
        f"| Потери RTK fixed | {m.fix_downgrades} |",
        f"| Скачки координат | {m.position_jumps} |",
        f"| Максимальный разрыв | {_fmt(m.max_gap_s, 'с')} |",
        f"| CEP50 / CEP95 / максимум | {_fmt(m.cep50_m, 'м', 4)} / {_fmt(m.cep95_m, 'м', 4)} / "
        f"{_fmt(m.max_error_m, 'м', 4)} |",
        f"| Медиана PDOP | {_fmt(m.pdop_median)} |",
        "",
        "Распределение качества решения: "
        + (", ".join(f"{k} — {v}" for k, v in m.quality_counts.items()) or "нет данных"),
        "",
        "Спутников в зоне видимости (максимум): "
        + (", ".join(f"{k} — {v}" for k, v in m.sats_in_view_max.items()) or "нет данных"),
        "",
        "## Поток данных", "",
        "| Показатель | Значение |", "|---|---|",
        f"| Байт | {s.bytes_total} |",
        f"| Валидных строк | {s.sentences_ok} |",
        f"| Ошибок контрольной суммы | {s.checksum_errors} |",
        f"| Ошибок обрамления | {s.framing_errors} |",
        f"| Оборванных строк | {s.truncated} |",
        f"| Слишком длинных строк | {s.overlong} |",
        f"| Ошибок в полях | {result.field_errors} |",
        f"| Мусорных байт | {s.garbage_bytes} |",
        f"| Строк длиннее 82 символов (вне стандарта) | {s.non_standard_length} |",
        "",
    ]
    if m.events:
        lines += ["## События", "", "| t, с | Событие | Описание |", "|---|---|---|"]
        lines += [f"| {e.t_s:.2f} | {e.kind} | {e.detail} |" for e in m.events[:100]]
        lines.append("")
    if result.errors:
        lines += ["## Первые ошибки разбора", "", "```", *result.errors[:20], "```", ""]
    return "\n".join(lines)


def to_junit_xml(checks: list[CheckResult], suite: str = "gnss-acceptance") -> str:
    """Каждый критерий — отдельный testcase: GitLab покажет их во вкладке Tests."""
    root = ET.Element("testsuites")
    ts = ET.SubElement(root, "testsuite", name=suite, tests=str(len(checks)),
                       failures=str(sum(not c.passed for c in checks)))
    for c in checks:
        case = ET.SubElement(ts, "testcase", classname=suite, name=f"{c.limit.key}: {c.title}")
        if not c.passed:
            ET.SubElement(case, "failure", message=c.message).text = c.message
        else:
            ET.SubElement(case, "system-out").text = c.message
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
