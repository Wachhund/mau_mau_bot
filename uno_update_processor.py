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
from typing import Awaitable, Callable, Optional, Tuple

from telegram import Update
from telegram.ext import BaseUpdateProcessor


logger = logging.getLogger(__name__)


GameKey = Tuple[int, Optional[int]]
GameResolver = Callable[[str], Optional[GameKey]]


class UnoUpdateProcessor(BaseUpdateProcessor):
    """Serializes updates that target the same (chat_id, thread_id).

    Inline queries and other updates without a derivable chat context run in
    parallel. ``ChosenInlineResult`` updates carry the game id in their
    ``result_id`` (format: ``<game_id>:<base_id>:<anti_cheat>``); the optional
    ``game_resolver`` callback maps that game id back to a ``(chat_id,
    thread_id)`` key.
    """

    def __init__(self, max_concurrent_updates: int,
                 game_resolver: Optional[GameResolver] = None):
        super().__init__(max_concurrent_updates=max_concurrent_updates)
        self._locks: dict[GameKey, asyncio.Lock] = {}
        self._game_resolver = game_resolver

    def _lock_for_key(self, key: GameKey) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def release_key(self, key: GameKey) -> None:
        """Drop the lock for a key once its game has ended."""
        self._locks.pop(key, None)

    def _key_for_update(self, update) -> Optional[GameKey]:
        msg = getattr(update, 'message', None) or getattr(update, 'edited_message', None)
        if msg is not None:
            chat = getattr(msg, 'chat', None)
            if chat is not None:
                return (chat.id, getattr(msg, 'message_thread_id', None))

        cb = getattr(update, 'callback_query', None)
        if cb is not None:
            cb_msg = getattr(cb, 'message', None)
            if cb_msg is not None:
                chat = getattr(cb_msg, 'chat', None)
                if chat is not None:
                    return (chat.id, getattr(cb_msg, 'message_thread_id', None))

        cir = getattr(update, 'chosen_inline_result', None)
        if cir is not None and self._game_resolver is not None:
            result_id = getattr(cir, 'result_id', '') or ''
            parts = result_id.split(':', 2)
            if len(parts) < 3:
                return None
            game_id = parts[0]
            if game_id == 'none':
                return None
            return self._game_resolver(game_id)

        return None

    async def do_process_update(self, update: Update,
                                coroutine: Awaitable[None]) -> None:
        key = self._key_for_update(update)
        if key is None:
            await coroutine
            return

        lock = self._lock_for_key(key)
        async with lock:
            await coroutine

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        self._locks.clear()
