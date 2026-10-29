"""Property-based тесты (hypothesis): инварианты на тысячах случайных входов.

Вместо «вот пример — вот ответ» проверяем свойства, которые должны
выполняться всегда. Hypothesis сам ищет контрпример и уменьшает его до
минимального — готовые шаги воспроизведения для баг-репорта.
"""

import contextlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gnss_testbench.analysis import analyze_bytes
from gnss_testbench.nmea import (
    NmeaError,
    NmeaStreamDecoder,
    build_sentence,
    decode_all,
    format_coord,
    parse,
    parse_coord,
    split_sentence,
)
from tests.conftest import gga

printable_body = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E, blacklist_characters="$*"),
    min_size=5,
    max_size=80,
).map(lambda s: "GPXXX," + s)


@given(printable_body)
def test_checksum_roundtrip(body):
    assert split_sentence(build_sentence(body)) == body.split(",")


@given(printable_body, st.integers(min_value=1), st.integers(min_value=1, max_value=255))
def test_any_single_byte_corruption_is_detected(body, pos_seed, delta):
    """Искажение любого одного символа тела всегда ловится контрольной суммой."""
    line = build_sentence(body)
    pos = 1 + pos_seed % len(body)
    new = chr((ord(line[pos]) + delta) % 95 + 0x20)
    if new in "$*" or new == line[pos]:
        return
    with pytest.raises(NmeaError):
        split_sentence(line[:pos] + new + line[pos + 1:])


@given(st.text(max_size=200))
def test_parser_never_crashes_on_arbitrary_text(text):
    """На любом входе — либо результат, либо NmeaError. Никаких IndexError/TypeError."""
    with contextlib.suppress(NmeaError):
        parse(text)


@given(st.lists(st.text(alphabet="0123456789.,-NSEWAV", max_size=12), min_size=1, max_size=20),
       st.sampled_from(["GPGGA", "GPRMC", "GPGSA", "GPGSV", "GPVTG"]))
def test_parser_never_crashes_on_valid_frame_with_random_fields(fields, address):
    """Самое интересное — корректное обрамление и мусор внутри полей."""
    with contextlib.suppress(NmeaError):
        parse(build_sentence(",".join([address, *fields])))


@given(st.floats(min_value=-90, max_value=90, allow_nan=False))
def test_latitude_roundtrip(value):
    text, hemi = format_coord(value, is_lat=True)
    assert parse_coord(text, hemi, is_lat=True) == pytest.approx(value, abs=1e-8)


@given(st.floats(min_value=-180, max_value=180, allow_nan=False))
def test_longitude_roundtrip(value):
    text, hemi = format_coord(value, is_lat=False)
    assert parse_coord(text, hemi, is_lat=False) == pytest.approx(value, abs=1e-8)


VALID_STREAM = b"".join(gga(utc=f"0900{s:02d}.00").encode() + b"\r\n" for s in range(20))


@given(st.lists(st.integers(min_value=1, max_value=50), min_size=1, max_size=200))
def test_decoder_is_chunking_invariant(sizes):
    """Как бы порт ни нарезал поток на куски, результат тот же."""
    decoder = NmeaStreamDecoder()
    out, pos, i = [], 0, 0
    while pos < len(VALID_STREAM):
        size = sizes[i % len(sizes)]
        out += decoder.feed(VALID_STREAM[pos:pos + size])
        pos, i = pos + size, i + 1
    assert out == decode_all(VALID_STREAM)[0]


@settings(max_examples=200)
@given(st.binary(max_size=2000))
def test_decoder_survives_random_bytes(data):
    lines, stats = decode_all(data)
    assert stats.bytes_total == len(data)
    for line in lines:
        split_sentence(line)            # всё, что вернул декодер, — валидно


@settings(max_examples=100)
@given(st.binary(max_size=500), st.binary(max_size=500))
def test_valid_sentences_survive_surrounding_noise(prefix, suffix):
    """Мусор до и после не должен съедать валидные строки посередине,
    если сам мусор не содержит '$' (иначе он честно открывает новую строку)."""
    prefix = prefix.replace(b"$", b"")
    lines, _ = decode_all(prefix + b"\r\n" + VALID_STREAM + suffix)
    assert len(lines) >= 20


@settings(max_examples=50, deadline=None)
@given(st.binary(max_size=3000))
def test_full_pipeline_never_crashes(data):
    analyze_bytes(VALID_STREAM[:500] + data + VALID_STREAM[500:])
