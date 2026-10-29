"""Декодер байтового потока с последовательного порта.

Порт отдаёт байты кусками произвольной длины: строка может прийти по частям,
между строками бывает мусор (шум при подключении, бинарные протоколы вроде
UBX/RTCM в том же порту), строка может оборваться посередине. Декодер
собирает из этого валидные NMEA-строки и ведёт статистику всех проблем —
это и есть материал для баг-репорта на прошивку.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parser import ChecksumError, NmeaError, split_sentence

#: Стандарт NMEA 0183 ограничивает строку 82 символами вместе с '$' и CRLF,
#: но RTK-приёмники с высокоточными координатами часто его превышают.
STANDARD_MAX_LEN = 82
DEFAULT_MAX_LEN = 160


@dataclass
class StreamStats:
    bytes_total: int = 0
    sentences_ok: int = 0
    checksum_errors: int = 0
    framing_errors: int = 0
    truncated: int = 0          # строку прервал новый '$' до конца строки
    overlong: int = 0           # строка длиннее max_len — потеряли конец строки
    garbage_bytes: int = 0      # байты вне строк
    non_standard_length: int = 0  # валидные, но длиннее 82 символов
    errors: list[str] = field(default_factory=list)

    @property
    def sentences_bad(self) -> int:
        return self.checksum_errors + self.framing_errors + self.truncated + self.overlong

    @property
    def bad_ratio(self) -> float:
        total = self.sentences_ok + self.sentences_bad
        return self.sentences_bad / total if total else 0.0


class NmeaStreamDecoder:
    """Собирает строки из потока байт: ``feed(chunk) -> list[str]``."""

    MAX_ERRORS_KEPT = 50

    def __init__(self, max_len: int = DEFAULT_MAX_LEN) -> None:
        self.max_len = max_len
        self.stats = StreamStats()
        self._buf = bytearray()
        self._in_sentence = False

    def _error(self, message: str) -> None:
        if len(self.stats.errors) < self.MAX_ERRORS_KEPT:
            self.stats.errors.append(message)

    def _finish(self) -> str | None:
        raw = bytes(self._buf)
        self._buf.clear()
        self._in_sentence = False
        line = raw.decode("ascii", errors="replace")
        try:
            split_sentence(line)
        except ChecksumError as exc:
            self.stats.checksum_errors += 1
            self._error(f"{exc}: {line!r}")
            return None
        except NmeaError as exc:
            self.stats.framing_errors += 1
            self._error(f"{exc}: {line!r}")
            return None
        self.stats.sentences_ok += 1
        if len(raw) + 2 > STANDARD_MAX_LEN:
            self.stats.non_standard_length += 1
        return line

    def feed(self, data: bytes) -> list[str]:
        self.stats.bytes_total += len(data)
        out: list[str] = []
        for byte in data:
            if byte == 0x24:                          # '$'
                if self._in_sentence:
                    self.stats.truncated += 1
                    self._error(f"строка оборвана: {bytes(self._buf)!r}")
                self._buf = bytearray(b"$")
                self._in_sentence = True
            elif byte in (0x0D, 0x0A):                # CR / LF
                if self._in_sentence:
                    line = self._finish()
                    if line is not None:
                        out.append(line)
            elif not self._in_sentence:
                self.stats.garbage_bytes += 1
            else:
                self._buf.append(byte)
                if len(self._buf) > self.max_len:
                    self.stats.overlong += 1
                    self._error(f"строка длиннее {self.max_len} байт: {bytes(self._buf[:40])!r}…")
                    self._buf.clear()
                    self._in_sentence = False
        return out

    def flush(self) -> list[str]:
        """Конец потока: недописанная строка считается оборванной."""
        if self._in_sentence:
            self.stats.truncated += 1
            self._error(f"поток закончился посреди строки: {bytes(self._buf)!r}")
            self._buf.clear()
            self._in_sentence = False
        return []


def decode_all(data: bytes, max_len: int = DEFAULT_MAX_LEN) -> tuple[list[str], StreamStats]:
    decoder = NmeaStreamDecoder(max_len)
    lines = decoder.feed(data)
    decoder.flush()
    return lines, decoder.stats
