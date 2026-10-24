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
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher

USER = User(id=1, is_bot=False, first_name="Иван")
USER2 = User(id=2, is_bot=False, first_name="Мария")


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
        if name == "GetMe":
            return User(id=42, is_bot=True, first_name="TestBot", username="test_bot")
        if name == "SendPhoto":
            return Message(
                message_id=500,
                date=datetime.now(),
                chat=Chat(id=int(getattr(method, "chat_id", 1)), type="private"),
                caption=getattr(method, "caption", None),
            )
        if name == "DeleteMessage":
            return True
        if name in {"SendMessage", "SendDocument", "EditMessageText"}:
            return Message(
                message_id=getattr(method, "message_id", None) or 1,
                date=datetime.now(),
                chat=Chat(id=int(getattr(method, "chat_id", 1)), type="private"),
                text=getattr(method, "text", None),
            )
        return True

    # -- помощники для проверок -------------------------------------------

    def photos(self) -> list[SendPhoto]:
        return [request for request in self.requests if isinstance(request, SendPhoto)]

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


def message_update(text: str, update_id: int = 1, user: User = USER) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(),
            chat=Chat(id=user.id, type="private"),
            from_user=user,
            text=text,
        ),
    )


def callback_update(data: str, update_id: int = 1, user: User = USER) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb-{data}",
            from_user=user,
            chat_instance="chat-instance",
            data=data,
            message=Message(
                message_id=1,
                date=datetime.now(),
                chat=Chat(id=user.id, type="private"),
                from_user=user,
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
            assert len(keyboard_buttons) == 7

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
            assert len(session.photos()) == 1

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

            # 12. Семья: создание.
            await send(callback_update("fam:menu"))
            assert "Семья" in session.last_text()

            await send(callback_update("fam:create"))
            assert "название" in session.last_text().lower()

            await send(message_update("Ивановы"))
            assert "создана" in session.last_text().lower()
            family = await db.get_family(1)
            assert family is not None

            # 13. Второй участник присоединяется по ссылке из приглашения.
            await send(message_update(f"/start join_{family.invite_code}", user=USER2))
            assert "присоединились" in session.last_text().lower()

            members = await db.get_family_members(family.id)
            assert {member.name for member in members} == {"Иван", "Мария"}

            # 14. Расход второго участника.
            categories2 = await db.list_categories(2, "expense")
            await send(callback_update("tx:new:expense", user=USER2))
            await send(callback_update(f"tx:pick:{categories2[0].id}", user=USER2))
            await send(message_update("700 продукты", user=USER2))
            assert "Записано" in session.last_text()

            # 15. Общий отчёт видит обоих и показывает, кто на что потратил.
            await send(callback_update("fam:rep:month"))
            family_report = session.last_text()
            assert "Ивановы" in family_report
            assert "Иван" in family_report
            assert "Мария" in family_report
            assert "700" in family_report
            assert "Продукты 700" in family_report
            assert len(session.photos()) == 2

            # 16. Общая история показывает автора операции.
            await send(callback_update("fam:history:0"))
            history_text = session.last_text()
            assert "История семьи" in history_text
            assert "Мария" in history_text

            # 17. Приглашение содержит ссылку на бота.
            await send(callback_update("fam:invite"))
            invite_text = session.last_text()
            assert "Приглашение" in invite_text
            assert "t.me/test_bot" in invite_text
            assert family.invite_code in invite_text

            # 18. Участники и выход владельца: права переходят Марии.
            await send(callback_update("fam:members"))
            assert "Участники семьи" in session.last_text()

            await send(callback_update("fam:leave_yes"))
            assert "вышли" in session.last_text().lower()
            assert await db.get_family(1) is None
            family_for_maria = await db.get_family(2)
            assert family_for_maria is not None
            assert family_for_maria.owner_id == 2

            # 19. Справка.
            await send(message_update("/help"))
            assert "Как пользоваться" in session.last_text()

            # 20. Неизвестный текст подсказывает меню.
            update_id += 100
            await send(message_update("привет", update_id=update_id))
            assert "Не понял" in session.last_text()
        finally:
            await db.close()
            await bot.session.close()

    asyncio.run(scenario())
