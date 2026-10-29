"""Сквозные тесты: эмулятор -> псевдотерминал -> pyserial -> декодер -> анализ -> приёмка.

Повторяют то, что делает HIL-стенд с реальным приёмником, только вместо
платы — виртуальный приёмник на pty. Время ускорено, чтобы прогон занимал секунды.
"""

import sys

import pytest

from gnss_testbench.analysis import Reference, analyze_bytes, evaluate, load_criteria
from gnss_testbench.capture import capture
from gnss_testbench.sim import VirtualReceiver, VirtualSerialPort, load_scenario
from tests.conftest import CRITERIA, SCENARIOS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="pty есть только в Linux/macOS"),
]

CASES = [
    # сценарий,              критерии,                  ускорение, ожидаемый вердикт
    ("open_sky_rtk",   "rtk_static.toml",        200, True),
    ("urban_canyon",   "rtk_static.toml",        200, False),
    ("tunnel_dropout", "rtk_static.toml",        100, False),
    ("noisy_serial",   "serial_robustness.toml",  60, True),
]


@pytest.mark.parametrize(("name", "criteria", "speed", "expected"), CASES, ids=[c[0] for c in CASES])
def test_scenario_through_serial_port(name, criteria, speed, expected):
    sc = load_scenario(SCENARIOS / f"{name}.toml")
    receiver = VirtualReceiver(sc)
    with VirtualSerialPort(receiver, speed=speed, autostart=False) as port:
        result = capture(port.port, duration_s=sc.duration_s / speed + 10,
                         stop_when=port.finished.is_set, on_open=port.start)

    # Через порт должно прийти ровно то, что выдал эмулятор — ни байта потерь
    assert result.data == VirtualReceiver(sc).to_bytes()

    analysis = analyze_bytes(result.data, Reference(sc.ref_lat, sc.ref_lon))
    checks = evaluate(analysis, load_criteria(CRITERIA / criteria))
    failed = [c.message for c in checks if not c.passed]
    assert all(c.passed for c in checks) is expected, failed


def test_data_sent_before_port_opened_is_lost():
    """BUG-003: pyserial при открытии порта сбрасывает буфер (tcflush).
    Подключение к уже вещающему приёмнику теряет начало потока, первая строка
    может прийти обрезанной — декодер обязан это пережить."""
    sc = load_scenario(SCENARIOS / "open_sky_rtk.toml")
    with VirtualSerialPort(VirtualReceiver(sc), speed=100) as port:   # вещание сразу
        port.finished.wait(timeout=1.0)                                  # часть потока уже ушла
        result = capture(port.port, duration_s=10, stop_when=port.finished.is_set)
    full = VirtualReceiver(sc).to_bytes()
    assert 0 < len(result.data) < len(full)
    assert full.endswith(result.data)                   # потеряно только начало
    assert analyze_bytes(result.data).stream.sentences_ok > 0


def test_capture_stops_at_max_sentences():
    sc = load_scenario(SCENARIOS / "open_sky_rtk.toml")
    with VirtualSerialPort(VirtualReceiver(sc), speed=50, autostart=False) as port:
        result = capture(port.port, duration_s=10, max_sentences=100, on_open=port.start)
    assert 100 <= result.sentences < 150
    assert result.elapsed_s < 10


@pytest.mark.parametrize("chunk_size", [1, 7, 512])
def test_uart_fragmentation_does_not_lose_data(chunk_size):
    sc = load_scenario(SCENARIOS / "noisy_serial.toml")
    with VirtualSerialPort(VirtualReceiver(sc), speed=100, chunk_size=chunk_size, autostart=False) as port:
        result = capture(port.port, duration_s=15, stop_when=port.finished.is_set, on_open=port.start)
    assert result.data == VirtualReceiver(sc).to_bytes()
