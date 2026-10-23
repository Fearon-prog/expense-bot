"""Локальный обходной слой для разработки на этой машине.

Из-за ограничений файловой песочницы каталоги, созданные Python с правами
0o700 (так делает tempfile), оказываются недоступны для записи — pip и venv
падают с PermissionError. Модуль меняет такой режим на 0o777 при создании
каталога. На код бота и на работу в обычном окружении это не влияет:
sitecustomize подключается только когда его каталог есть в PYTHONPATH.
"""

from __future__ import annotations

import os

_original_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *, dir_fd=None):  # type: ignore[no-untyped-def]
    if mode == 0o700:
        mode = 0o777
    return _original_mkdir(path, mode, dir_fd=dir_fd)


os.mkdir = _mkdir  # type: ignore[assignment]
