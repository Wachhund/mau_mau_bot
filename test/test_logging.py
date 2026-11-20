"""Log messages carry the game, chat, topic and user they concern."""

import logging
from datetime import datetime

import pytest
from telegram import Chat, Message, Update, User
from telegram.error import Forbidden

from game import Game
from utils import error, safe_call


class _FakeContext:
    def __init__(self, exc):
        self.error = exc


def test_game_str_names_chat_and_topic():
    game = Game(Chat(-100, 'supergroup', title='Friends'))
    assert str(game) == f'game {game.id} in "Friends" (chat -100)'

    game.thread_id = 5
    assert str(game) == f'game {game.id} in "Friends" (chat -100, topic 5)'


@pytest.mark.asyncio
async def test_safe_call_logs_telegram_error_as_one_line(caplog):
    async def send_message():
        raise Forbidden("bot was blocked by the user")

    with caplog.at_level(logging.WARNING, logger='utils'):
        assert await safe_call(send_message(), 42) is None

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert record.getMessage() == \
        "send_message to chat 42 failed: bot was blocked by the user"


@pytest.mark.asyncio
async def test_safe_call_logs_other_errors_with_traceback(caplog):
    async def send_message():
        raise ValueError("boom")

    with caplog.at_level(logging.WARNING, logger='utils'):
        assert await safe_call(send_message()) is None

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_error_handler_names_chat_topic_and_user(caplog):
    message = Message(1, datetime.now(), Chat(-100, 'supergroup'),
                      from_user=User(7, 'u', is_bot=False),
                      is_topic_message=True, message_thread_id=5)
    update = Update(1, message=message)

    with caplog.at_level(logging.ERROR, logger='utils'):
        await error(update, _FakeContext(ValueError("boom")))

    [record] = caplog.records
    assert record.getMessage() == \
        "Unhandled exception in update handler (chat -100, topic 5, user 7)"
