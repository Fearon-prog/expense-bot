"""Запуск: python -m bot."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram.exceptions import TelegramUnauthorizedError

from .config import ConfigError
from .main import main
from .singleton import AlreadyRunning


def run() -> None:
    try:
        asyncio.run(main())
    except ConfigError as exc:
        logging.error("%s", exc)
        sys.exit(1)
    except AlreadyRunning as exc:
        logging.error("%s", exc)
        # Код 2 означает «уже запущен» — внешний цикл перезапуска это учитывает.
        sys.exit(2)
    except TelegramUnauthorizedError:
        logging.error(
            "Telegram отклонил токен (401 Unauthorized). "
            "Проверьте BOT_TOKEN в .env — возможно, токен отозван в @BotFather."
        )
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("Остановлено пользователем")
    except SystemExit:
        raise
    except Exception:
        logging.exception("Бот остановлен из-за непредвиденной ошибки")
        sys.exit(1)


if __name__ == "__main__":
    run()
