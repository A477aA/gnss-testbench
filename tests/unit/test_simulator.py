"""Эмулятор приёмника: сценарии, детерминизм, внесение дефектов."""

import pytest

from gnss_testbench.analysis import Reference, analyze_bytes
from gnss_testbench.nmea import decode_all, parse
from gnss_testbench.sim import ScenarioError, VirtualReceiver, from_dict, load_scenario
from tests.conftest import SCENARIOS

BASE = {
    "name": "test",
    "rate_hz": 1,
    "seed": 1,
    "reference": {"lat": 55.6948, "lon": 37.36125, "alt_m": 185.3},
    "phase": [
        {"duration_s": 5, "quality": "NO_FIX", "sats": 4},
        {"duration_s": 15, "quality": "RTK_FIXED", "sats": 18, "hdop": 0.7, "sigma_m": 0.01},
    ],
}


def scenario(**overrides):
    return from_dict({**BASE, **overrides})


def run(sc):
    return analyze_bytes(VirtualReceiver(sc).to_bytes(), Reference(sc.ref_lat, sc.ref_lon))


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.toml")), ids=lambda p: p.stem)
def test_repository_scenarios_load_and_produce_valid_nmea(path):
    sc = load_scenario(path)
    data = VirtualReceiver(sc).to_bytes()
    lines, _ = decode_all(data)
    assert lines
    for line in lines[:200]:
        parse(line)                        # не должно бросать исключений


def test_same_seed_same_bytes():
    assert VirtualReceiver(scenario()).to_bytes() == VirtualReceiver(scenario()).to_bytes()


def test_different_seed_different_noise():
    assert VirtualReceiver(scenario(seed=1)).to_bytes() != VirtualReceiver(scenario(seed=2)).to_bytes()


def test_clean_scenario_has_no_stream_errors():
    r = run(scenario())
    assert r.stream.sentences_bad == 0
    assert r.field_errors == 0
    assert r.metrics.epochs == 20
    assert r.metrics.ttff_s == 5
    assert r.metrics.sats_in_view_max.keys() == {"GPS", "GLONASS"}


def test_phase_noise_matches_sigma():
    """При σ = 1 см на ось CEP95 горизонтальной ошибки ≈ 2.45σ."""
    long = {**BASE, "phase": [{"duration_s": 2000, "quality": "RTK_FIXED", "sats": 18, "sigma_m": 0.01}]}
    m = run(from_dict(long)).metrics
    assert m.cep95_m == pytest.approx(0.0245, rel=0.1)


def test_bias_shifts_mean():
    biased = {**BASE, "phase": [{"duration_s": 300, "quality": "RTK_FIXED", "sats": 18,
                                 "sigma_m": 0.005, "bias_east_m": 0.05}]}
    m = run(from_dict(biased)).metrics
    assert m.mean_offset_enu_m[0] == pytest.approx(0.05, abs=0.002)


def test_dropout_removes_epochs():
    m = run(scenario(faults={"dropouts": [{"start_s": 10, "duration_s": 3}]})).metrics
    assert m.epochs == 17
    assert m.max_gap_s == 4


def test_corrupt_checksum_at_exact_time():
    r = run(scenario(faults={"corrupt_checksum_at_s": [7, 12]}))
    assert r.stream.checksum_errors == 2
    assert r.metrics.epochs == 18          # у двух эпох потеряна GGA


def test_truncate_fault():
    r = run(scenario(faults={"truncate_at_s": [8]}))
    assert r.stream.truncated == 1


def test_garbage_fault():
    r = run(scenario(faults={"garbage_probability": 1.0}))
    assert r.stream.garbage_bytes > 0
    assert r.stream.sentences_bad == 0     # мусор между строками не портит сами строки


def test_jump_fault_detected():
    r = run(scenario(faults={"jumps": [{"at_s": 10, "east_m": 1.0, "duration_s": 2}]}))
    assert r.metrics.position_jumps == 2


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"rate_hz": 0}, "rate_hz"),
        ({"rate_hz": 1000}, "rate_hz"),
        ({"phase": []}, "хотя бы одна фаза"),
        ({"phase": [{"duration_s": 0, "quality": "GPS"}]}, "положительной"),
        ({"phase": [{"duration_s": 1, "quality": "SUPER_FIX"}]}, "неизвестное качество"),
        ({"phase": [{"duration_s": 1, "quality": "GPS", "sigma_m": -1}]}, "sigma_m"),
        ({"reference": {"lat": 91, "lon": 0}}, "опорная точка"),
        ({"faults": {"garbage_probability": 1.5}}, "вероятность"),
        ({"start_utc": "9 утра"}, "hh:mm:ss"),
    ],
)
def test_invalid_scenarios(override, reason):
    with pytest.raises(ScenarioError, match=reason):
        scenario(**override)


def test_missing_reference():
    data = {k: v for k, v in BASE.items() if k != "reference"}
    with pytest.raises(ScenarioError, match="reference"):
        from_dict(data)
