"""Командная строка: gnss-testbench {simulate,serve,capture,analyze,run}.

Коды возврата: 0 — успех, 1 — критерии приёмки не выполнены, 2 — ошибка запуска.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from . import __version__
from .analysis import (
    AnalysisResult,
    CheckResult,
    CriteriaError,
    Reference,
    analyze_bytes,
    evaluate,
    load_criteria,
    to_json,
    to_junit_xml,
    to_markdown,
)
from .sim import ScenarioError, VirtualReceiver, VirtualSerialPort, load_scenario


def _write_reports(result: AnalysisResult, checks: list[CheckResult] | None,
                   args: argparse.Namespace, title: str) -> None:
    md = to_markdown(result, checks, title)
    if args.markdown:
        args.markdown.write_text(md, encoding="utf-8")
    if args.json:
        args.json.write_text(to_json(result, checks), encoding="utf-8")
    if args.junit and checks is not None:
        args.junit.write_text(to_junit_xml(checks, suite=title), encoding="utf-8")
    if not args.quiet:
        print(md)


def _verdict(checks: list[CheckResult] | None) -> int:
    if checks is None:
        return 0
    for c in checks:
        if not c.passed:
            print(f"FAIL  {c.message}", file=sys.stderr)
    return 0 if all(c.passed for c in checks) else 1


def cmd_simulate(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    data = VirtualReceiver(scenario).to_bytes()
    args.output.write_bytes(data)
    print(f"{scenario.name}: {len(data)} байт, {scenario.duration_s:g} с -> {args.output}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    with VirtualSerialPort(VirtualReceiver(scenario), speed=args.speed) as port:
        print(f"Виртуальный приёмник «{scenario.name}» вещает в {port.port}", flush=True)
        print("Подключиться: picocom -b 115200 " + port.port + "  (Ctrl+C — остановить)", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            port.finished.wait()
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from .capture import capture  # pyserial нужен только здесь

    result = capture(args.port, baudrate=args.baud, duration_s=args.duration)
    args.output.write_bytes(result.data)
    print(f"Записано {len(result.data)} байт, {result.sentences} валидных строк "
          f"за {result.elapsed_s:.1f} с -> {args.output}")
    return 0 if result.sentences else 1


def _analyze(data: bytes, args: argparse.Namespace, title: str) -> int:
    reference = Reference.parse(args.reference) if args.reference else None
    result = analyze_bytes(data, reference, jump_threshold_m=args.jump_threshold)
    checks = evaluate(result, load_criteria(args.criteria)) if args.criteria else None
    _write_reports(result, checks, args, title)
    return _verdict(checks)


def cmd_analyze(args: argparse.Namespace) -> int:
    return _analyze(args.log.read_bytes(), args, args.title or f"Анализ {args.log.name}")


def cmd_run(args: argparse.Namespace) -> int:
    """Сценарий -> поток -> анализ -> приёмка, опорная точка берётся из сценария."""
    scenario = load_scenario(args.scenario)
    data = VirtualReceiver(scenario).to_bytes()
    if args.save_log:
        args.save_log.write_bytes(data)
    args.reference = args.reference or f"{scenario.ref_lat},{scenario.ref_lon}"
    return _analyze(data, args, args.title or scenario.name)


def _add_report_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--criteria", type=Path, help="TOML с критериями приёмки")
    p.add_argument("--reference", help="опорная точка 'lat,lon' для оценки точности")
    p.add_argument("--jump-threshold", type=float, default=0.5, metavar="M",
                   help="порог скачка координат между эпохами, м (по умолчанию 0.5)")
    p.add_argument("--markdown", type=Path, help="сохранить отчёт в Markdown")
    p.add_argument("--json", type=Path, help="сохранить отчёт в JSON")
    p.add_argument("--junit", type=Path, help="сохранить результаты приёмки в JUnit XML")
    p.add_argument("--title", help="заголовок отчёта")
    p.add_argument("-q", "--quiet", action="store_true", help="не печатать отчёт")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gnss-testbench",
                                 description="Стенд тестирования ПО GNSS-приёмников")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("simulate", help="сгенерировать лог по сценарию")
    p.add_argument("scenario", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("serve", help="вещать сценарий в виртуальный последовательный порт")
    p.add_argument("scenario", type=Path)
    p.add_argument("--speed", type=float, default=1.0, help="ускорение времени (по умолчанию 1.0)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("capture", help="записать поток с последовательного порта")
    p.add_argument("--port", required=True, help="например /dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--duration", type=float, default=60.0, help="секунд записи")
    p.add_argument("-o", "--output", type=Path, required=True)
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("analyze", help="проанализировать лог и проверить критерии")
    p.add_argument("log", type=Path)
    _add_report_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("run", help="прогнать сценарий целиком: эмуляция + анализ + приёмка")
    p.add_argument("scenario", type=Path)
    p.add_argument("--save-log", type=Path, help="сохранить сгенерированный лог")
    _add_report_args(p)
    p.set_defaults(func=cmd_run)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ScenarioError, CriteriaError, ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
