"""Полный цикл: байты -> строки -> сообщения -> эпохи -> метрики."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..nmea import NmeaError, Sentence, StreamStats, decode_all, parse
from .epochs import build_epochs
from .metrics import Metrics, Reference, compute_metrics


@dataclass
class AnalysisResult:
    stream: StreamStats
    metrics: Metrics
    field_errors: int = 0
    unsupported: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def bad_sentence_ratio(self) -> float:
        bad = self.stream.sentences_bad + self.field_errors
        total = self.stream.sentences_ok + self.stream.sentences_bad
        return round(bad / total, 6) if total else 0.0


def analyze_bytes(
    data: bytes,
    reference: Reference | None = None,
    *,
    jump_threshold_m: float = 0.5,
) -> AnalysisResult:
    lines, stream = decode_all(data)
    sentences: list[Sentence] = []
    field_errors, unsupported = 0, 0
    errors = list(stream.errors)
    for line in lines:
        try:
            msg = parse(line)
        except NmeaError as exc:
            field_errors += 1
            errors.append(f"{exc}: {line!r}")
            continue
        if msg is None:
            unsupported += 1
        else:
            sentences.append(msg)
    metrics = compute_metrics(build_epochs(sentences), reference, jump_threshold_m=jump_threshold_m)
    return AnalysisResult(stream, metrics, field_errors, unsupported, errors[:50])


def analyze_file(path: Path, reference: Reference | None = None, **kwargs: float) -> AnalysisResult:
    return analyze_bytes(path.read_bytes(), reference, **kwargs)
