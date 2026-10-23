"""Защита от запуска второго экземпляра бота."""

from __future__ import annotations

import socket

import pytest

from bot.singleton import AlreadyRunning, acquire_lock


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_second_instance_is_rejected() -> None:
    port = _free_port()

    first = acquire_lock(port)
    try:
        with pytest.raises(AlreadyRunning):
            acquire_lock(port)
    finally:
        first.close()

    # После освобождения порт снова доступен.
    second = acquire_lock(port)
    second.close()
