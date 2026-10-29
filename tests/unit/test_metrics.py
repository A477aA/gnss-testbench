"""Сборка эпох и метрики на вручную построенных потоках с известным ответом."""

import pytest

from gnss_testbench.analysis import Reference, analyze_bytes, build_epochs
from gnss_testbench.geo import offset_position
from gnss_testbench.nmea import build_sentence, format_coord, format_time, parse
from tests.conftest import gga

REF = Reference(55.6948, 37.36125)


def stream(qualities: list[int], *, start: float = 9 * 3600, rate: float = 1.0,
           skip: set[int] = frozenset(), offsets: dict[int, tuple[float, float]] | None = None) -> bytes:
    """Поток GGA: одна эпоха на элемент qualities; skip — пропущенные эпохи."""
    offsets = offsets or {}
    out = []
    for i, q in enumerate(qualities):
        if i in skip:
            continue
        lat, lon = offset_position(REF.lat, REF.lon, *offsets.get(i, (0.0, 0.0)))
        la, ns = format_coord(lat, is_lat=True)
        lo, ew = format_coord(lon, is_lat=False)
        out.append(gga(utc=format_time(start + i / rate), quality=q, lat=la, ns=ns, lon=lo, ew=ew))
    return ("\r\n".join(out) + "\r\n").encode()


# --- Эпохи -----------------------------------------------------------------------

def test_gsa_gsv_attach_to_last_timed_epoch():
    lines = [
        build_sentence("GPGSV,1,1,01,05,45,180,40"),            # до первой эпохи — отбрасывается
        gga(utc="090000.00"),
        build_sentence("GNGSA,A,3,05,06,,,,,,,,,,,1.5,0.8,1.2,1"),
        build_sentence("GLGSV,1,1,03,65,30,120,40,66,10,200,35,67,50,90,44"),
        gga(utc="090001.00"),
    ]
    epochs = build_epochs([parse(line) for line in lines])
    assert [e.t for e in epochs] == [32400.0, 32401.0]
    assert epochs[0].pdop == 1.5
    assert epochs[0].sats_in_view == {"GLONASS": 3}
    assert epochs[1].gsa == []


def test_rmc_and_gga_with_same_time_merge():
    rmc = build_sentence("GNRMC,090000.00,A,5541.6880,N,03721.6750,E,0.0,,291026,,,D")
    (epoch,) = build_epochs([parse(line) for line in (rmc, gga(utc="090000.00"))])
    assert epoch.gga is not None
    assert epoch.rmc is not None


def test_midnight_rollover_keeps_order():
    data = stream([4] * 4, start=86400 - 2)
    m = analyze_bytes(data, REF).metrics
    assert m.duration_s == 3
    assert m.gaps == []


# --- Метрики --------------------------------------------------------------------

def test_ttff_and_time_to_rtk():
    m = analyze_bytes(stream([0] * 10 + [1] * 5 + [5] * 5 + [4] * 10), REF).metrics
    assert m.ttff_s == 10
    assert m.time_to_rtk_fixed_s == 20
    assert m.quality_counts == {"NO_FIX": 10, "GPS": 5, "RTK_FLOAT": 5, "RTK_FIXED": 10}
    assert m.availability == pytest.approx(20 / 30, abs=1e-4)


def test_never_fixed():
    m = analyze_bytes(stream([0] * 20), REF).metrics
    assert m.ttff_s is None
    assert m.time_to_rtk_fixed_s is None
    assert m.rtk_fixed_ratio is None
    assert m.cep95_m is None


def test_downgrades_counted_per_loss():
    m = analyze_bytes(stream([4, 4, 5, 4, 4, 1, 1, 4, 4, 4]), REF).metrics
    assert m.fix_downgrades == 2
    assert [e.t_s for e in m.events if e.kind == "downgrade"] == [2, 5]


def test_gap_detected_and_counts_against_rtk_ratio():
    """Пропавшие эпохи — не «RTK fixed»: доля считается от ожидаемых эпох."""
    m = analyze_bytes(stream([4] * 20, skip={10, 11, 12}), REF).metrics
    assert m.gaps == [(9.0, 4.0)]
    assert m.max_gap_s == 4.0
    assert m.rtk_fixed_ratio == pytest.approx(17 / 20)
    assert m.fix_downgrades == 0        # пропуск данных — не потеря фиксации


def test_rate_estimated_at_10hz():
    m = analyze_bytes(stream([4] * 50, rate=10), REF).metrics
    assert m.rate_hz == pytest.approx(10)
    assert m.max_gap_s == pytest.approx(0.1)


def test_position_jump_out_and_back():
    m = analyze_bytes(stream([4] * 10, offsets={5: (0.8, 0.0)}), REF).metrics
    assert m.position_jumps == 2            # туда и обратно
    assert m.max_error_m == pytest.approx(0.8, abs=1e-3)


def test_jump_threshold_is_configurable():
    data = stream([4] * 10, offsets={5: (0.3, 0.0)})
    assert analyze_bytes(data, REF).metrics.position_jumps == 0
    assert analyze_bytes(data, REF, jump_threshold_m=0.2).metrics.position_jumps == 2


def test_accuracy_known_offsets():
    """10 эпох со смещением 1..10 см на восток: CEP50 = 5.5 см, CEP95 = 9.55 см."""
    offsets = {i: ((i + 1) / 100, 0.0) for i in range(10)}
    m = analyze_bytes(stream([4] * 10, offsets=offsets), REF).metrics
    assert m.cep50_m == pytest.approx(0.055, abs=1e-4)
    assert m.cep95_m == pytest.approx(0.0955, abs=1e-4)
    assert m.max_error_m == pytest.approx(0.10, abs=1e-4)
    assert m.mean_offset_enu_m == pytest.approx((0.055, 0.0), abs=1e-4)


def test_accuracy_uses_only_rtk_fixed():
    m = analyze_bytes(stream([1, 5, 4, 4], offsets={0: (5.0, 0), 1: (0.5, 0)}), REF).metrics
    assert m.max_error_m == pytest.approx(0.0, abs=1e-4)


def test_no_reference_no_accuracy():
    m = analyze_bytes(stream([4] * 5)).metrics
    assert m.cep50_m is None


def test_reference_parse():
    assert Reference.parse("55.6948,37.36125") == REF
    with pytest.raises(ValueError, match="lat,lon"):
        Reference.parse("55.6948")


def test_field_errors_counted_separately_from_stream_errors():
    bad_field = build_sentence("GNGGA,090000.00,5541.6880,N,03721.6750,E,9,18,0.7,185.3,M,14.2,M,,")
    data = stream([4] * 3) + bad_field.encode() + b"\r\n"
    r = analyze_bytes(data, REF)
    assert r.stream.sentences_bad == 0
    assert r.field_errors == 1
    assert r.bad_sentence_ratio == pytest.approx(1 / 4)


def test_empty_input():
    r = analyze_bytes(b"")
    assert r.metrics.epochs == 0
    assert r.bad_sentence_ratio == 0
