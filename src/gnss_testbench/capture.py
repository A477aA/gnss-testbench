"""Захват потока с последовательного порта (реальный приёмник или pty)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import serial  # pyserial

from .nmea import NmeaStreamDecoder


@dataclass
class CaptureResult:
    data: bytes
    sentences: int
    elapsed_s: float


def capture(
    port: str,
    *,
    baudrate: int = 115200,
    duration_s: float = 10.0,
    max_sentences: int | None = None,
    stop_when: Callable[[], bool] | None = None,
    on_open: Callable[[], None] | None = None,
) -> CaptureResult:
    """Читает порт, пока не истечёт время, не наберётся max_sentences
    валидных строк или не сработает stop_when (и данных больше нет).

    on_open вызывается сразу после открытия порта — например, чтобы
    запустить эмулятор или подать приёмнику команду на старт.
    """
    decoder = NmeaStreamDecoder()
    buf = bytearray()
    count = 0
    start = time.monotonic()
    with serial.Serial(port, baudrate=baudrate, timeout=0.1) as ser:
        if on_open is not None:
            on_open()
        while time.monotonic() - start < duration_s:
            chunk = ser.read(4096)
            if chunk:
                buf += chunk
                count += len(decoder.feed(chunk))
                if max_sentences is not None and count >= max_sentences:
                    break
            elif stop_when is not None and stop_when():
                break
    return CaptureResult(bytes(buf), count, time.monotonic() - start)
