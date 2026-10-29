"""Поля: координаты, время, дата. Граничные значения и классы эквивалентности."""

from datetime import date, time

import pytest

from gnss_testbench.nmea import FieldError, format_coord, format_time, parse_coord, parse_date, parse_time


@pytest.mark.parametrize(
    ("value", "hemi", "is_lat", "expected"),
    [
        ("4807.038", "N", True, 48.1173),
        ("4807.038", "S", True, -48.1173),
        ("01131.000", "E", False, 11.5166667),
        ("01131.000", "W", False, -11.5166667),
        ("0000.000", "N", True, 0.0),             # экватор
        ("9000.000", "N", True, 90.0),            # полюс — верхняя граница
        ("9000.000", "S", True, -90.0),
        ("18000.000", "W", False, -180.0),        # антимеридиан
        ("5959.9999", "N", True, 59.9999983),     # минуты чуть меньше 60
        ("5541.6880000", "N", True, 55.6948),     # высокоточный формат RTK
    ],
)
def test_valid_coordinates(value, hemi, is_lat, expected):
    assert parse_coord(value, hemi, is_lat=is_lat) == pytest.approx(expected, abs=1e-7)


@pytest.mark.parametrize(
    ("value", "hemi", "is_lat", "reason"),
    [
        ("9000.001", "N", True, "вне диапазона"),     # за полюсом
        ("18000.001", "E", False, "вне диапазона"),
        ("4860.000", "N", True, "минут"),             # минуты = 60
        ("4807.038", "E", True, "полушарие"),         # долготное полушарие у широты
        ("4807.038", "", True, "полушарие"),
        ("807.038", "N", True, "формат"),             # потерян ведущий ноль
        ("1131.000", "E", False, "формат"),
        ("48O7.038", "N", True, "формат"),            # буква O вместо нуля
        ("4807", "N", True, "формат"),
    ],
)
def test_invalid_coordinates(value, hemi, is_lat, reason):
    with pytest.raises(FieldError, match=reason):
        parse_coord(value, hemi, is_lat=is_lat)


def test_empty_coordinate_is_none():
    assert parse_coord("", "", is_lat=True) is None


@pytest.mark.parametrize("value", [0.0, 55.6948, -33.8688, 89.9999999, -0.0000001])
def test_format_parse_roundtrip_lat(value):
    text, hemi = format_coord(value, is_lat=True)
    assert parse_coord(text, hemi, is_lat=True) == pytest.approx(value, abs=1e-8)


@pytest.mark.parametrize("value", [0.0, 37.36125, -122.4194, 179.9999999, -180.0])
def test_format_parse_roundtrip_lon(value):
    text, hemi = format_coord(value, is_lat=False)
    assert parse_coord(text, hemi, is_lat=False) == pytest.approx(value, abs=1e-8)


def test_format_coord_minutes_rounding_carry():
    """59.99999999' округляется до 60' — должен быть перенос в градусы, а не '5560.0'."""
    text, _ = format_coord(55 + 59.999999999 / 60, is_lat=True)
    assert text == "5600.0000000"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123519", time(12, 35, 19)),
        ("123519.25", time(12, 35, 19, 250000)),
        ("000000.00", time(0, 0, 0)),
        ("235959.99", time(23, 59, 59, 990000)),
        ("", None),
    ],
)
def test_time(value, expected):
    assert parse_time(value) == expected


@pytest.mark.parametrize("value", ["240000", "126000", "123560", "12ab00", "1235"])
def test_invalid_time(value):
    with pytest.raises(FieldError):
        parse_time(value)


@pytest.mark.parametrize(("seconds", "expected"), [(0, "000000.00"), (33015.25, "091015.25"),
                                                    (86399.5, "235959.50"), (86400, "000000.00")])
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("291026", date(2026, 10, 29)),
        ("230394", date(1994, 3, 23)),    # регрессия BUG-001: был 2094 год
        ("010180", date(1980, 1, 1)),     # граница: начало эпохи GPS
        ("311279", date(2079, 12, 31)),   # граница: последний год «20yy»
        ("290224", date(2024, 2, 29)),    # високосный
        ("", None),
    ],
)
def test_date(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize("value", ["290223", "320126", "011326", "2910261", "29-10-26"])
def test_invalid_date(value):
    with pytest.raises(FieldError):
        parse_date(value)
