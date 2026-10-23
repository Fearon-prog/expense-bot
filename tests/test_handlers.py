"""Сквозной тест: апдейты проходят через настоящий Dispatcher и роутеры.

Telegram не вызывается — вместо HTTP-сессии подставлен FakeSession,
который запоминает исходящие методы. Так проверяется вся связка:
фильтры, middleware, FSM, клавиатуры, работа с базой.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    EditMessageText,
    SendDocument,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher

USER = User(id=1, is_bot=False, first_name="Иван")


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any):  # noqa: ANN201
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod,
        timeout: int | None = None,
    ) -> Any:
        self.requests.append(method)
        name = type(method).__name__
        if name in {"SendMessage", "SendDocument", "EditMessageText"}:
            return Message(
                message_id=getattr(method, "message_id", None) or 1,
                date=datetime.now(),
                chat=Chat(id=int(getattr(method, "chat_id", 1)), type="private"),
                text=getattr(method, "text", None),
            )
        return True

    # -- помощники для проверок -------------------------------------------

    def texts(self) -> list[str]:
        return [
            request.text
            for request in self.requests
            if isinstance(request, (SendMessage, EditMessageText)) and request.text
        ]

    def last_text(self) -> str:
        texts = self.texts()
        assert texts, "бот не отправил ни одного сообщения"
        return texts[-1]

    def last_message(self) -> Message | None:
        for request in reversed(self.requests):
            if isinstance(request, SendMessage):
                return request  # type: ignore[return-value]
        return None


def message_update(text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(),
            chat=Chat(id=1, type="private"),
            from_user=USER,
            text=text,
        ),
    )


def callback_update(data: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb-{data}",
            from_user=USER,
            chat_instance="chat-instance",
            data=data,
            message=Message(
                message_id=1,
                date=datetime.now(),
                chat=Chat(id=1, type="private"),
                from_user=USER,
                text="предыдущее сообщение",
            ),
        ),
    )


def test_full_user_flow(tmp_path) -> None:
    async def scenario() -> None:
        db_path = tmp_path / "bot.db"
        db = Database(db_path)
        await db.connect()
        config = Config(
            bot_token="42:TEST",
            db_path=db_path,
            default_timezone="Europe/Moscow",
            currency="₽",
        )
        dispatcher = build_dispatcher(db, config)
        session = FakeSession()
        bot = Bot(
            token="42:TEST",
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        update_id = 0

        async def send(update: Update) -> None:
            await dispatcher.feed_update(bot, update)
            assert not any("Что-то пошло не так" in text for text in session.texts())

        try:
            # 1. Старт и главное меню.
            await send(message_update("/start"))
            assert "Привет" in session.last_text()
            start_message = session.last_message()
            assert start_message is not None
            keyboard_buttons = [
                button
                for row in start_message.reply_markup.inline_keyboard  # type: ignore[union-attr]
                for button in row
            ]
            assert len(keyboard_buttons) == 6

            # 2. Выбор категории расхода.
            await send(callback_update("tx:new:expense"))
            assert "Выберите категорию" in session.last_text()

            categories = await db.list_categories(1, "expense")
            assert len(categories) == 12

            await send(callback_update(f"tx:pick:{categories[0].id}"))
            assert "Введите сумму" in session.last_text()

            # 3. Запись операции «450 такси».
            await send(message_update("450 такси"))
            assert "Записано" in session.last_text()
            assert "такси" in session.last_text()
            assert await db.count_transactions(1) == 1

            transaction = (await db.list_transactions(1, 1, 0))[0]

            # 4. Отмена последней операции.
            await send(callback_update(f"tx:undo:{transaction.id}"))
            assert "Удалено" in session.last_text()
            assert await db.count_transactions(1) == 0

            # 5. Новая операция и отчёт за месяц.
            await send(callback_update("tx:new:expense"))
            await send(callback_update(f"tx:pick:{categories[0].id}"))
            await send(message_update("1 200,50 обед с коллегами"))
            assert "Записано" in session.last_text()

            # 6. Доход.
            income_categories = await db.list_categories(1, "income")
            await send(callback_update("tx:new:income"))
            await send(callback_update(f"tx:pick:{income_categories[0].id}"))
            await send(message_update("50 000 зарплата"))
            assert "Записано" in session.last_text()
            assert await db.count_transactions(1) == 2

            await send(callback_update("rep:month"))
            report = session.last_text()
            assert "Отчёт" in report
            assert "1\u202f200,50" in report
            assert "50\u202f000" in report
            assert "Расходы по категориям" in report

            # 7. История.
            await send(callback_update("hist:page:0"))
            assert "История операций" in session.last_text()
            assert "обед с коллегами" in session.last_text()

            # 8. Добавление своей категории.
            await send(callback_update("cat:kind:expense"))
            assert "Категории расходов" in session.last_text()

            await send(callback_update("cat:new:expense"))
            assert "Новая категория" in session.last_text()

            await send(message_update("Такси"))
            assert "создана" in session.last_text()
            categories = await db.list_categories(1, "expense")
            assert any(category.name == "Такси" for category in categories)

            # 9. Переименование.
            taxi = next(category for category in categories if category.name == "Такси")
            await send(callback_update(f"cat:ren:{taxi.id}"))
            await send(message_update("Такси и каршеринг"))
            assert "переименована" in session.last_text()
            taxi = await db.get_category(1, taxi.id)
            assert taxi is not None and taxi.name == "Такси и каршеринг"

            # 10. Удаление пустой категории.
            await send(callback_update(f"cat:del:{taxi.id}"))
            assert "Категории расходов" in session.last_text()
            assert await db.get_category(1, taxi.id) is None

            # 11. Экспорт CSV.
            await send(callback_update("exp:csv"))
            documents = [
                request for request in session.requests if isinstance(request, SendDocument)
            ]
            assert len(documents) == 1
            document = documents[0].document
            payload = document.data.decode("utf-8-sig")
            assert "Дата;Тип;Категория" in payload
            assert "Расход" in payload

            # 12. Справка.
            await send(message_update("/help"))
            assert "Как пользоваться" in session.last_text()

            # 13. Неизвестный текст подсказывает меню.
            update_id += 100
            await send(message_update("привет", update_id=update_id))
            assert "Не понял" in session.last_text()
        finally:
            await db.close()
            await bot.session.close()

    asyncio.run(scenario())
