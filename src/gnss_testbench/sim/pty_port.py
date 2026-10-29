"""Виртуальный последовательный порт на псевдотерминале (Linux/macOS).

Эмулятор пишет в master-сторону pty, а тест или утилита захвата открывает
slave-сторону (``/dev/pts/N``) через pyserial — ровно как ``/dev/ttyUSB0``
с реальным приёмником. Так интеграционные тесты проверяют весь путь
«порт -> декодер -> анализ» без железа.
"""

from __future__ import annotations

import os
import threading
import time
import tty
from types import TracebackType

from .receiver import VirtualReceiver


class VirtualSerialPort:
    """Запускает поток, который выдаёт сценарий в pty в темпе эмуляции.

    speed — множитель времени: 1.0 — реальное время, 50 — в 50 раз быстрее.
    autostart=False — вещание начинается только по start(). Это нужно тестам:
    pyserial при открытии порта сбрасывает входной буфер (tcflush), и всё,
    что пришло до открытия, теряется — ровно как с реальным приёмником.
    """

    def __init__(self, receiver: VirtualReceiver, *, speed: float = 1.0, chunk_size: int = 64,
                 autostart: bool = True) -> None:
        if speed <= 0:
            raise ValueError("speed должен быть положительным")
        self.receiver = receiver
        self.speed = speed
        self.autostart = autostart
        self.chunk_size = chunk_size
        self._stop = threading.Event()
        self.finished = threading.Event()
        self._thread: threading.Thread | None = None
        self._master = self._slave = -1
        self.port = ""

    def __enter__(self) -> VirtualSerialPort:
        self._master, self._slave = os.openpty()
        tty.setraw(self._slave)                 # без эха и преобразования CRLF
        self.port = os.ttyname(self._slave)
        if self.autostart:
            self.start()
        return self

    def start(self) -> None:
        """Начать вещание (повторный вызов ничего не делает)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="virtual-gnss", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        start = time.monotonic()
        try:
            for epoch in self.receiver.epochs():
                delay = start + epoch.t_s / self.speed - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    return
                # Пишем кусками: реальный UART тоже не отдаёт строки целиком
                for i in range(0, len(epoch.data), self.chunk_size):
                    os.write(self._master, epoch.data[i:i + self.chunk_size])
                if self._stop.is_set():
                    return
        except OSError:
            return                                # порт закрыли во время записи
        finally:
            self.finished.set()

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        for fd in (self._master, self._slave):
            if fd >= 0:
                os.close(fd)
