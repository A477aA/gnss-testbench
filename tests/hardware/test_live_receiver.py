"""Тесты на реальном приёмнике. По умолчанию пропускаются.

Запуск на стенде (приёмник на USB, антенна на открытом небе):

    pytest -m hardware --gnss-port /dev/ttyUSB0 --gnss-duration 120

В CI — job на раннере с тегом gnss-bench, к которому подключён приёмник.
"""

import pytest

from gnss_testbench.analysis import analyze_bytes
from gnss_testbench.capture import capture

pytestmark = pytest.mark.hardware


@pytest.fixture(scope="module")
def live(request):
    opt = request.config.getoption
    result = capture(opt("--gnss-port"), baudrate=opt("--gnss-baud"), duration_s=opt("--gnss-duration"))
    return analyze_bytes(result.data)


def test_receiver_outputs_valid_nmea(live):
    assert live.stream.sentences_ok > 0, "приёмник молчит: проверь порт, скорость и питание"


def test_stream_is_clean(live):
    assert live.bad_sentence_ratio < 0.001, live.errors[:5]


def test_output_rate_is_stable(live):
    assert live.metrics.rate_hz is not None
    assert live.metrics.max_gap_s <= 2 / live.metrics.rate_hz


def test_receiver_gets_a_fix(live):
    assert live.metrics.ttff_s is not None, "за время записи решения не было: антенна видит небо?"


def test_sees_multiple_constellations(live):
    assert len(live.metrics.sats_in_view_max) >= 2, live.metrics.sats_in_view_max
