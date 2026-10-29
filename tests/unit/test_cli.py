"""Командная строка и коды возврата — на них завязан CI."""

import json

import pytest

from gnss_testbench.cli import main
from tests.conftest import CRITERIA, SCENARIOS

OPEN_SKY = str(SCENARIOS / "open_sky_rtk.toml")
URBAN = str(SCENARIOS / "urban_canyon.toml")
RTK = str(CRITERIA / "rtk_static.toml")


def test_run_passes_on_open_sky(tmp_path):
    md, js, junit = tmp_path / "r.md", tmp_path / "r.json", tmp_path / "r.xml"
    code = main(["run", OPEN_SKY, "--criteria", RTK, "-q",
                 "--markdown", str(md), "--json", str(js), "--junit", str(junit)])
    assert code == 0
    assert "ПРОЙДЕНА" in md.read_text()
    assert json.loads(js.read_text())["acceptance"]["passed"] is True
    assert "<testsuite" in junit.read_text()


def test_run_fails_on_urban_canyon(capsys):
    assert main(["run", URBAN, "--criteria", RTK, "-q"]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_simulate_then_analyze(tmp_path):
    log = tmp_path / "open_sky.nmea"
    assert main(["simulate", OPEN_SKY, "-o", str(log)]) == 0
    assert log.stat().st_size > 0
    assert main(["analyze", str(log), "--criteria", RTK, "--reference", "55.6948,37.36125", "-q"]) == 0


def test_analyze_without_criteria_always_zero(tmp_path, capsys):
    log = tmp_path / "x.nmea"
    main(["simulate", URBAN, "-o", str(log)])
    assert main(["analyze", str(log)]) == 0
    assert "# Анализ x.nmea" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "нет-такого-файла.toml"],
        ["analyze", "нет-такого-файла.nmea"],
        ["run", OPEN_SKY, "--reference", "кривая"],
    ],
)
def test_usage_errors_return_2(argv, capsys):
    assert main(argv) == 2
    assert "Ошибка" in capsys.readouterr().err


def test_bad_criteria_file_returns_2(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[acceptance]\nttf_max_s = 1\n")
    assert main(["run", OPEN_SKY, "--criteria", str(bad), "-q"]) == 2
