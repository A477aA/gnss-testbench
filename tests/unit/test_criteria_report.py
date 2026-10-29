"""Критерии приёмки и отчёты."""

import json
import xml.etree.ElementTree as ET

import pytest

from gnss_testbench.analysis import (
    CRITERIA,
    CriteriaError,
    Reference,
    analyze_bytes,
    evaluate,
    load_criteria,
    parse_limit,
    to_json,
    to_junit_xml,
    to_markdown,
)
from tests.conftest import CRITERIA as CRITERIA_DIR
from tests.unit.test_metrics import stream

REF = Reference(55.6948, 37.36125)


@pytest.mark.parametrize(
    ("key", "metric", "op"),
    [
        ("ttff_max_s", "ttff", "<="),
        ("time_to_rtk_fixed_max_s", "time_to_rtk_fixed", "<="),
        ("rtk_fixed_ratio_min", "rtk_fixed_ratio", ">="),
        ("max_gap_max_s", "max_gap", "<="),          # 'max' внутри имени метрики
        ("cep95_max_m", "cep95", "<="),
        ("pdop_median_max", "pdop_median", "<="),
    ],
)
def test_parse_limit(key, metric, op):
    limit = parse_limit(key, 1)
    assert (limit.metric, limit.op, limit.value) == (metric, op, 1.0)


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("ttf_max_s", 60, "неизвестный критерий"),        # опечатка
        ("ttff", 60, "неизвестный критерий"),             # нет направления
        ("ttff_maxs", 60, "неизвестный критерий"),
        ("ttff_max_s", "60", "числом"),
        ("ttff_max_s", True, "числом"),                   # bool — подкласс int, но не порог
    ],
)
def test_parse_limit_rejects(key, value, reason):
    with pytest.raises(CriteriaError, match=reason):
        parse_limit(key, value)


def test_every_metric_has_a_getter():
    r = analyze_bytes(stream([0, 1, 4, 4]), REF)
    for name, spec in CRITERIA.items():
        value = spec.getter(r)
        assert value is None or isinstance(value, (int, float)), name


@pytest.mark.parametrize("path", sorted(CRITERIA_DIR.glob("*.toml")), ids=lambda p: p.name)
def test_repository_criteria_files_are_valid(path):
    assert load_criteria(path)


def test_criteria_file_without_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("ttff_max_s = 1\n", encoding="utf-8")
    with pytest.raises(CriteriaError, match=r"\[acceptance\]"):
        load_criteria(p)


def test_evaluate_boundaries():
    r = analyze_bytes(stream([0] * 10 + [4] * 10), REF)       # TTFF ровно 10 с
    checks = evaluate(r, [parse_limit("ttff_max_s", 10), parse_limit("ttff_max_s", 9.99),
                          parse_limit("rtk_fixed_ratio_min", 1.0)])
    assert [c.passed for c in checks] == [True, False, True]


def test_missing_metric_fails_check():
    r = analyze_bytes(stream([0] * 5), REF)
    (check,) = evaluate(r, [parse_limit("ttff_max_s", 60)])
    assert not check.passed
    assert "не получена" in check.message


def test_junit_xml_structure():
    r = analyze_bytes(stream([0] * 5 + [4] * 5), REF)
    checks = evaluate(r, [parse_limit("ttff_max_s", 60), parse_limit("ttff_max_s", 1)])
    root = ET.fromstring(to_junit_xml(checks, suite="demo"))
    suite = root.find("testsuite")
    assert suite.get("tests") == "2"
    assert suite.get("failures") == "1"
    cases = suite.findall("testcase")
    assert cases[0].find("failure") is None
    assert "FAIL" in cases[1].find("failure").get("message")


def test_markdown_and_json_reports():
    r = analyze_bytes(stream([0] * 5 + [4] * 5), REF)
    checks = evaluate(r, [parse_limit("ttff_max_s", 1)])
    md = to_markdown(r, checks, title="Демо")
    assert md.startswith("# Демо")
    assert "НЕ ПРОЙДЕНА" in md
    data = json.loads(to_json(r, checks))
    assert data["acceptance"]["passed"] is False
    assert data["metrics"]["ttff_s"] == 5
