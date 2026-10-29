"""Обрамление строки и контрольная сумма."""

import pytest

from gnss_testbench.nmea import (
    ChecksumError,
    FramingError,
    NmeaError,
    build_sentence,
    checksum,
    split_sentence,
)

# Классические примеры из описаний NMEA 0183 (gpsd, NMEA reference manual)
REFERENCE = [
    "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
    "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
    "$GPGSA,A,3,04,05,,09,12,,,24,,,,,2.5,1.3,2.1*39",
    "$GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75",
    "$GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48",
]
GGA_REF = REFERENCE[0]


@pytest.mark.parametrize("line", REFERENCE)
def test_reference_sentences_are_valid(line):
    assert split_sentence(line)[0].startswith("GP")


def test_checksum_is_xor_of_body():
    assert checksum("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,") == "47"


def test_build_sentence_roundtrip():
    assert build_sentence("GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,") == GGA_REF


@pytest.mark.parametrize("suffix", ["\r\n", "\n", "\r", "  "])
def test_line_endings_tolerated(suffix):
    assert split_sentence(GGA_REF + suffix)


def test_lowercase_checksum_accepted():
    assert split_sentence(GGA_REF[:-2] + "47".lower())


@pytest.mark.parametrize(
    ("line", "error", "reason"),
    [
        pytest.param(GGA_REF[:-2] + "48", ChecksumError, "не совпала", id="wrong-sum"),
        pytest.param(GGA_REF.replace("4807.038", "4807.039"), ChecksumError, "не совпала", id="payload-bit"),
        pytest.param(GGA_REF.replace(",M,", ",m,", 1), ChecksumError, "не совпала", id="case-change"),
        pytest.param(GGA_REF.split("*")[0], FramingError, "нет контрольной суммы", id="no-asterisk"),
        pytest.param(GGA_REF[1:], FramingError, "начинаться", id="no-dollar"),
        pytest.param(GGA_REF[:-1], FramingError, "2 символов", id="short-sum"),
        pytest.param(GGA_REF + "0", FramingError, "2 символов", id="long-sum"),
        pytest.param("", FramingError, "начинаться", id="empty"),
        pytest.param(build_sentence("gpgga,1"), FramingError, "адрес", id="lowercase-address"),
        pytest.param(build_sentence("GPGG,1"), FramingError, "адрес", id="short-address"),
    ],
)
def test_broken_sentences_rejected(line, error, reason):
    with pytest.raises(error, match=reason):
        split_sentence(line)


def test_error_hierarchy():
    """Вызывающий код может ловить общий NmeaError, а тесты — конкретный тип."""
    assert issubclass(ChecksumError, NmeaError)
    assert issubclass(FramingError, NmeaError)
