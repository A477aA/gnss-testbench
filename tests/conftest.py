from __future__ import annotations

from pathlib import Path

import pytest

from gnss_testbench.nmea import build_sentence

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"
CRITERIA = ROOT / "criteria"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("gnss", "реальный GNSS-приёмник")
    group.addoption("--gnss-port", help="порт приёмника для hardware-тестов, например /dev/ttyUSB0")
    group.addoption("--gnss-baud", type=int, default=115200)
    group.addoption("--gnss-duration", type=float, default=60.0, help="секунд записи с приёмника")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--gnss-port"):
        return
    skip = pytest.mark.skip(reason="нужен реальный приёмник: --gnss-port /dev/ttyUSB0")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


def gga(
    utc: str = "090000.00",
    quality: int = 4,
    lat: str = "5541.6880000",
    ns: str = "N",
    lon: str = "03721.6750000",
    ew: str = "E",
    sats: int = 18,
    hdop: str = "0.7",
) -> str:
    if quality == 0:
        return build_sentence(f"GNGGA,{utc},,,,,0,{sats:02d},,,M,,M,,")
    return build_sentence(f"GNGGA,{utc},{lat},{ns},{lon},{ew},{quality},{sats:02d},{hdop},"
                          f"185.300,M,14.200,M,1.0,0001")


@pytest.fixture
def make_gga():
    return gga
