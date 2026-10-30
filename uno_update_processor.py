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


"""Custom UpdateProcessor that serializes updates per (chat_id, thread_id)."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Optional, Tuple

from telegram import Update
from telegram.ext import BaseUpdateProcessor

from result_id import PSEUDO_GAME_ID, decode_result_id


logger = logging.getLogger(__name__)


GameKey = Tuple[int, Optional[int]]
GameResolver = Callable[[str], Optional[GameKey]]


def topic_id(message) -> Optional[int]:
    """The forum topic a message was sent in, or ``None``.

    Telegram also fills ``message_thread_id`` for replies in ordinary
    supergroups (the id of the reply thread), so the value only means a topic
    when ``is_topic_message`` is set. Messages in a forum's General topic
    carry neither and map to ``None`` like messages in a normal group.
    """
    if message is None or not message.is_topic_message:
        return None
    return message.message_thread_id


class _KeyLock:
    """A lock plus the number of tasks holding or waiting for it."""

    __slots__ = ('lock', 'users')

    def __init__(self):
        self.lock = asyncio.Lock()
        self.users = 0


class UnoUpdateProcessor(BaseUpdateProcessor):
    """Serializes updates that target the same (chat_id, thread_id).

    Inline queries and other updates without a derivable chat context run in
    parallel. ``ChosenInlineResult`` updates carry the game id in their
    ``result_id`` (format: ``<game_id>:<base_id>:<anti_cheat>``); the
    ``game_resolver`` callback maps that game id back to a ``(chat_id,
    thread_id)`` key. A service message about a member leaving concerns games
    in every topic of the chat, so it runs unkeyed and the handler takes each
    game's lock in turn via :meth:`serialized`.
    """

    def __init__(self, max_concurrent_updates: int,
                 game_resolver: Optional[GameResolver] = None):
        super().__init__(max_concurrent_updates=max_concurrent_updates)
        self._locks: dict[GameKey, _KeyLock] = {}
        self._game_resolver = game_resolver

    @asynccontextmanager
    async def serialized(self, key: GameKey):
        """Run the block while holding the lock for ``key``.

        Used by :meth:`do_process_update` and by code that runs outside the
        update flow but touches a game, such as the job-queue skip timer. The
        entry for a key exists only while a task holds or waits for it, so
        ended games leave nothing behind and a task still inside the block can
        never be joined by another task on a fresh lock for the same key.
        """
        entry = self._locks.get(key)
        if entry is None:
            entry = self._locks[key] = _KeyLock()
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0 and self._locks.get(key) is entry:
                del self._locks[key]

    def _key_for_update(self, update) -> Optional[GameKey]:
        # update.effective_message covers Message, EditedMessage and the
        # CallbackQuery.message case in a single attribute lookup.
        msg = update.effective_message
        if msg is not None and msg.chat is not None:
            if msg.left_chat_member is not None:
                return None
            return (msg.chat.id, topic_id(msg))

        cir = update.chosen_inline_result
        if cir is not None and self._game_resolver is not None:
            decoded = decode_result_id(cir.result_id or '')
            if decoded is None or decoded.game_id == PSEUDO_GAME_ID:
                return None
            return self._game_resolver(decoded.game_id)

        return None

    async def do_process_update(self, update: Update,
                                coroutine: Awaitable[None]) -> None:
        # Runs inside the base class's concurrency slot, so an update waiting
        # for a busy chat holds a slot while it waits. max_concurrent_updates
        # is set generously for that reason (shared_vars.py).
        key = self._key_for_update(update)
        if key is None:
            await coroutine
            return

        async with self.serialized(key):
            await coroutine

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        self._locks.clear()
