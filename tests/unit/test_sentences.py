"""Разбор сообщений GGA, RMC, GSA, GSV, VTG."""

from datetime import date, time

import pytest

from gnss_testbench.nmea import (
    GGA,
    GSA,
    GSV,
    RMC,
    VTG,
    FieldError,
    FixMode,
    FixQuality,
    SatInView,
    build_sentence,
    parse,
)
from tests.conftest import gga

# --- GGA -----------------------------------------------------------------------


def test_gga_reference():
    msg = parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47")
    assert msg == GGA("GP", time(12, 35, 19), 48.1173, pytest.approx(11.5166667), FixQuality.GPS,
                      8, 0.9, 545.4, 46.9, None, None)


def test_gga_rtk_fixed_high_precision():
    msg = parse(gga(utc="091530.20"))
    assert isinstance(msg, GGA)
    assert msg.quality is FixQuality.RTK_FIXED
    assert msg.has_fix
    assert msg.utc == time(9, 15, 30, 200000)
    assert msg.correction_age_s == 1.0
    assert msg.station_id == "0001"
    assert msg.lat == pytest.approx(55.6948)


@pytest.mark.parametrize("quality", list(FixQuality))
def test_all_fix_qualities(quality):
    assert parse(gga(quality=int(quality))).quality is quality


@pytest.mark.parametrize("raw", ["9", "-1", "X", "44"])
def test_unknown_fix_quality(raw):
    line = build_sentence(f"GNGGA,090000.00,5541.68800,N,03721.67500,E,{raw},18,0.7,185.3,M,14.2,M,,")
    with pytest.raises(FieldError):
        parse(line)


def test_gga_no_fix_cold_start():
    msg = parse(gga(quality=0, sats=3))
    assert msg.quality is FixQuality.NO_FIX
    assert not msg.has_fix
    assert (msg.lat, msg.lon, msg.hdop) == (None, None, None)
    assert msg.satellites == 3


def test_gga_fix_without_coordinates_is_inconsistent():
    """Прошивка заявляет решение, но координат нет — это дефект, а не «нет данных»."""
    with pytest.raises(FieldError, match="координаты пустые"):
        parse(build_sentence("GNGGA,090000.00,,,,,4,18,0.7,185.3,M,14.2,M,1.0,0001"))


def test_gga_truncated_fields():
    with pytest.raises(FieldError, match="минимум 15 полей"):
        parse(build_sentence("GNGGA,090000.00,5541.6880,N"))


@pytest.mark.parametrize(("field", "value"), [(7, "1O"), (8, "0,7"), (9, "abc")])
def test_gga_non_numeric_fields(field, value):
    fields = gga()[1:-3].split(",")
    fields[field] = value
    with pytest.raises(FieldError):
        parse(build_sentence(",".join(fields)))


# --- RMC -----------------------------------------------------------------------


def test_rmc_reference():
    msg = parse("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
    assert isinstance(msg, RMC)
    assert msg.valid
    assert msg.speed_knots == 22.4
    assert msg.course_deg == 84.4
    assert msg.date == date(1994, 3, 23)


def test_rmc_void():
    msg = parse(build_sentence("GNRMC,090000.00,V,,,,,,,291026,,,N"))
    assert not msg.valid
    assert msg.lat is None


def test_rmc_bad_status():
    with pytest.raises(FieldError, match="'A' или 'V'"):
        parse(build_sentence("GNRMC,090000.00,X,,,,,,,291026,,,N"))


# --- GSA -----------------------------------------------------------------------


def test_gsa_reference():
    msg = parse("$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39")
    assert msg == GSA("GP", True, FixMode.FIX_3D, (4, 5, 9, 12, 24), 2.5, 1.3, 2.1, None)


def test_gsa_nmea41_system_id():
    msg = parse(build_sentence("GNGSA,A,3,65,66,67,,,,,,,,,,1.2,0.7,1.0,2"))
    assert msg.system_id == 2
    assert msg.prns == (65, 66, 67)


@pytest.mark.parametrize(("mode", "fix"), [("X", "3"), ("A", "4"), ("A", "0")])
def test_gsa_invalid_modes(mode, fix):
    with pytest.raises(FieldError):
        parse(build_sentence(f"GPGSA,{mode},{fix},04,,,,,,,,,,,,2.5,1.3,2.1"))


# --- GSV -----------------------------------------------------------------------


def test_gsv_reference():
    msg = parse("$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75")
    assert isinstance(msg, GSV)
    assert (msg.total_msgs, msg.msg_num, msg.sats_in_view) == (2, 1, 8)
    assert msg.sats[0] == SatInView(1, 40, 83, 46)
    assert len(msg.sats) == 4


def test_gsv_satellite_not_tracked_has_empty_snr():
    msg = parse(build_sentence("GLGSV,1,1,02,65,30,120,,66,10,200,35"))
    assert msg.sats[0].snr_dbhz is None
    assert msg.sats[1].snr_dbhz == 35


def test_gsv_nmea41_signal_id_tail():
    msg = parse(build_sentence("GPGSV,1,1,01,05,45,180,40,1"))
    assert msg.sats == (SatInView(5, 45, 180, 40),)


@pytest.mark.parametrize(
    "body",
    [
        "GPGSV,2,3,08,01,40,083,46",       # часть 3 из 2
        "GPGSV,2,0,08,01,40,083,46",       # часть 0
        "GPGSV,1,1,01,01,91,083,46",       # угол места > 90
        "GPGSV,1,1,01,01,40,360,46",       # азимут 360
        "GPGSV,1,1,01,01,40,083,100",      # SNR > 99
        "GPGSV,1,1,01,01,40,083",          # неполный блок спутника
        "GPGSV,,1,01,01,40,083,46",        # пустое служебное поле
    ],
)
def test_gsv_invalid(body):
    with pytest.raises(FieldError):
        parse(build_sentence(body))


# --- VTG и прочее ------------------------------------------------------------------


def test_vtg_reference():
    assert parse("$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48") == VTG("GP", 54.7, 5.5, 10.2)


def test_unsupported_sentence_returns_none():
    assert parse(build_sentence("GPZDA,123519,29,10,2026,00,00")) is None
