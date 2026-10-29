"""Декодер байтового потока: всё, что бывает на реальном UART."""

import pytest

from gnss_testbench.nmea import NmeaStreamDecoder, decode_all
from tests.conftest import gga

A = gga(utc="090000.00").encode()
B = gga(utc="090001.00").encode()
CRLF = b"\r\n"


def test_clean_stream():
    lines, stats = decode_all(A + CRLF + B + CRLF)
    assert lines == [A.decode(), B.decode()]
    assert stats.sentences_ok == 2
    assert stats.sentences_bad == 0
    assert stats.bad_ratio == 0


@pytest.mark.parametrize("chunk", [1, 2, 7, 64, 4096])
def test_chunking_does_not_matter(chunk):
    data = (A + CRLF + B + CRLF) * 5
    dec = NmeaStreamDecoder()
    out = []
    for i in range(0, len(data), chunk):
        out += dec.feed(data[i:i + chunk])
    assert len(out) == 10
    assert dec.stats.bytes_total == len(data)


@pytest.mark.parametrize("ending", [b"\n", b"\r", b"\r\n", b"\n\r"])
def test_any_line_ending(ending):
    lines, _ = decode_all(A + ending + B + ending)
    assert len(lines) == 2


def test_garbage_between_sentences_is_counted_and_skipped():
    binary = bytes([0xB5, 0x62, 0x01, 0x07, 0x00, 0xFF])        # похоже на заголовок UBX
    lines, stats = decode_all(binary + A + CRLF + b"noise" + B + CRLF)
    assert len(lines) == 2
    assert stats.garbage_bytes == len(binary) + len(b"noise")


def test_truncated_sentence_detected_by_next_dollar():
    lines, stats = decode_all(A[:30] + B + CRLF)
    assert lines == [B.decode()]
    assert stats.truncated == 1


def test_stream_ends_mid_sentence():
    lines, stats = decode_all(A + CRLF + B[:20])
    assert len(lines) == 1
    assert stats.truncated == 1


def test_checksum_error_counted():
    lines, stats = decode_all(A[:-2] + b"00" + CRLF + B + CRLF)
    assert len(lines) == 1
    assert stats.checksum_errors == 1
    assert "контрольная сумма" in stats.errors[0]


def test_non_ascii_byte_inside_sentence_is_rejected():
    damaged = A[:20] + b"\xff" + A[21:]
    _, stats = decode_all(damaged + CRLF)
    assert stats.checksum_errors == 1


def test_overlong_line_dropped_and_decoder_recovers():
    endless = b"$GPGGA," + b"9" * 500             # потерян конец строки
    lines, stats = decode_all(endless + A + CRLF)
    assert lines == [A.decode()]
    assert stats.overlong == 1


def test_non_standard_length_counted_but_accepted():
    """Высокоточные GGA длиннее 82 символов — валидны, но отмечаются."""
    assert len(A) + 2 > 82
    lines, stats = decode_all(A + CRLF)
    assert len(lines) == 1
    assert stats.non_standard_length == 1


def test_error_log_is_bounded():
    _, stats = decode_all((A[:-2] + b"00" + CRLF) * 500)
    assert stats.checksum_errors == 500
    assert len(stats.errors) == NmeaStreamDecoder.MAX_ERRORS_KEPT


def test_empty_stream():
    lines, stats = decode_all(b"")
    assert lines == []
    assert stats.bad_ratio == 0
