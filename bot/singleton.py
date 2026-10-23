"""Защита от запуска второго экземпляра бота.

Два процесса с одним токеном конфликтуют: Telegram отдаёт обновления только
одному, второй получает 409 Conflict. Поэтому при старте бот занимает
локальный порт — второй экземпляр сразу понимает, что уже запущен.
"""

from __future__ import annotations

import socket

LOCK_PORT = 47613


class AlreadyRunning(RuntimeError):
    """Бот уже запущен в другом процессе."""


def acquire_lock(port: int = LOCK_PORT) -> socket.socket:
    """Занимает порт-«замок». Сокет закрывается вместе с процессом."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
    except OSError as exc:
        sock.close()
        raise AlreadyRunning(
            f"Порт {port} занят: похоже, бот уже запущен в другом окне "
            "или в автозагрузке."
        ) from exc
    return sock
