import math

import pytest

from gnss_testbench.geo import EARTH_RADIUS_M, enu_offset, horizontal_error, offset_position, percentile


def test_one_degree_latitude_is_about_111_km():
    assert horizontal_error(56.0, 37.0, 55.0, 37.0) == pytest.approx(111_195, rel=1e-4)


def test_longitude_shrinks_with_latitude():
    at_equator = horizontal_error(0.0, 1.0, 0.0, 0.0)
    at_moscow = horizontal_error(55.75, 1.0, 55.75, 0.0)
    assert at_moscow == pytest.approx(at_equator * math.cos(math.radians(55.75)), rel=1e-9)


@pytest.mark.parametrize(("east", "north"), [(0.0, 0.0), (0.01, -0.02), (1.5, 2.0), (-100.0, 250.0)])
def test_offset_roundtrip(east, north):
    lat, lon = offset_position(55.6948, 37.36125, east, north)
    e, n = enu_offset(lat, lon, 55.6948, 37.36125)
    assert (e, n) == pytest.approx((east, north), abs=1e-6)


def test_earth_radius_is_mean_radius():
    assert pytest.approx(6_371_000, rel=1e-4) == EARTH_RADIUS_M


@pytest.mark.parametrize(
    ("p", "expected"),
    [(0, 1.0), (50, 3.0), (100, 5.0), (25, 2.0), (95, 4.8)],
)
def test_percentile_linear_interpolation(p, expected):
    assert percentile([5, 1, 4, 2, 3], p) == pytest.approx(expected)


def test_percentile_single_value():
    assert percentile([0.42], 95) == 0.42


@pytest.mark.parametrize(("values", "p", "reason"), [([], 50, "пустая"), ([1.0], -1, "0..100"), ([1.0], 101, "0..100")])
def test_percentile_invalid(values, p, reason):
    with pytest.raises(ValueError, match=reason):
        percentile(values, p)
