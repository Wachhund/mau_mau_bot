#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Telegram bot to play UNO in group chats
# Copyright (c) 2016 Jannes Höke <uno@jhoeke.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


import asyncio
import logging
import time

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from internationalization import _, __
from shared_vars import gm
from uno_update_processor import topic_id

logger = logging.getLogger(__name__)

_admin_cache = {}
_admin_cache_timeout = 60 * 60

_background_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro):
    """Run a coroutine in the background and return its task.

    Call it with any async function, just leave off the await. The task is
    referenced until it finishes, and a failure is logged.

    Example:
        fire_and_forget(bot.send_message(chat_id, text="Hello!"))
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_task_done)
    return task


def _background_task_done(task):
    _background_tasks.discard(task)

    if task.cancelled():
        logger.warning("Background task %s was cancelled", task.get_name())
        return

    exc = task.exception()
    if exc is not None:
        logger.error("Background task failed", exc_info=exc)


async def drain_background_tasks(application=None):
    """Wait for the background tasks to finish. Wired as the Application's
    post_stop callback, so pending sends complete before the bot shuts down."""
    await asyncio.gather(*_background_tasks, return_exceptions=True)


def list_subtract(list1, list2):
    """ Helper function to subtract two lists and return the sorted result """
    list1 = list1.copy()

    for x in list2:
        list1.remove(x)

    return list(sorted(list1))


def display_name(user):
    """ Get the current players name including their username, if possible """
    user_name = user.first_name
    if user.username:
        user_name += ' (@' + user.username + ')'
    return user_name


def log_name(user):
    """A user's name and Telegram id, for log messages."""
    return f"{display_name(user)} [{user.id}]"


def display_color(color):
    """ Convert a color code to actual color name """
    if color == "r":
        return _("{emoji} Red").format(emoji='❤️')
    if color == "b":
        return _("{emoji} Blue").format(emoji='💙')
    if color == "g":
        return _("{emoji} Green").format(emoji='💚')
    if color == "y":
        return _("{emoji} Yellow").format(emoji='💛')


def display_color_group(color, game):
    """ Convert a color code to actual color name """
    if color == "r":
        return __("{emoji} Red", game.translate).format(
            emoji='❤️')
    if color == "b":
        return __("{emoji} Blue", game.translate).format(
            emoji='💙')
    if color == "g":
        return __("{emoji} Green", game.translate).format(
            emoji='💚')
    if color == "y":
        return __("{emoji} Yellow", game.translate).format(
            emoji='💛')


async def error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log the exception PTB caught.

    Uses ``exc_info=`` so the real traceback is attached: ``logger.exception``
    only walks the active exception context (``sys.exc_info()``), which is
    empty here because this handler runs after PTB has already swallowed
    the exception.
    """
    exc = getattr(context, 'error', None) if context is not None else None
    if exc is not None:
        logger.error("Unhandled exception in update handler (%s)",
                     _describe_update(update), exc_info=exc)
    else:
        logger.error("Error handler invoked without context.error")


def _describe_update(update):
    """Where an update came from: chat, topic and user ids."""
    if not isinstance(update, Update):
        return "no update"
    parts = []
    if update.effective_chat:
        parts.append(f"chat {update.effective_chat.id}")
    topic = topic_id(update.effective_message)
    if topic is not None:
        parts.append(f"topic {topic}")
    if update.effective_user:
        parts.append(f"user {update.effective_user.id}")
    return ", ".join(parts) or f"update {update.update_id}"


async def safe_call(coro, chat_id=None):
    """Await a bot call, logging a failure instead of raising.

    Use it where a failed request must not abort the handler. Network
    timeouts are configured on the Application builder (``shared_vars.py``).
    Telegram errors (blocked bot, timeouts, flood limits) get one warning
    line; anything else gets a traceback.

    Example:
        await safe_call(bot.send_sticker(chat_id, sticker=file_id), chat_id)
    """
    name = getattr(coro, '__name__', 'Bot call')
    try:
        return await coro
    except TelegramError as e:
        if chat_id is None:
            logger.warning("%s failed: %s", name, e)
        else:
            logger.warning("%s to chat %s failed: %s", name, chat_id, e)
        return None
    except Exception:
        logger.exception("%s failed", name)
        return None


async def send_async(bot, *args, **kwargs):
    """Send a message; a failed send is logged, not raised."""
    chat_id = args[0] if args else kwargs.get('chat_id')
    return await safe_call(bot.send_message(*args, **kwargs), chat_id)


async def answer_async(bot, *args, **kwargs):
    """Answer an inline query; a failure is logged, not raised."""
    return await safe_call(bot.answer_inline_query(*args, **kwargs))


def game_is_running(game):
    return gm.games_by_id.get(game.id) is game


def user_is_creator(user, game):
    return user.id in game.owner


async def user_is_creator_or_admin(user, game, bot, chat):
    return user_is_creator(user, game) or await user_is_admin(bot, chat, user)


async def user_is_admin(bot, chat, user):
    admin_ids = await get_admin_ids(bot, chat.id)
    return user.id in admin_ids


async def get_admin_ids(bot, chat_id):
    """Returns a list of admin IDs for a given chat. Results are cached for 1 hour."""
    now = time.time()
    if chat_id in _admin_cache:
        ids, timestamp = _admin_cache[chat_id]
        if now - timestamp < _admin_cache_timeout:
            return ids
    admins = await bot.get_chat_administrators(chat_id)
    ids = [admin.user.id for admin in admins]
    _admin_cache[chat_id] = (ids, now)
    return ids
