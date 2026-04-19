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
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from uno_update_processor import UnoUpdateProcessor


def _make_message_update(chat_id, thread_id=None):
    """Build a minimal Update-like object with .message.chat.id + thread."""
    return SimpleNamespace(
        message=SimpleNamespace(
            chat=SimpleNamespace(id=chat_id),
            message_thread_id=thread_id,
        ),
        edited_message=None,
        callback_query=None,
        chosen_inline_result=None,
        inline_query=None,
    )


def _make_callback_update(chat_id, thread_id=None):
    return SimpleNamespace(
        message=None,
        edited_message=None,
        callback_query=SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id=chat_id),
                message_thread_id=thread_id,
            )
        ),
        chosen_inline_result=None,
        inline_query=None,
    )


def _make_chosen_inline_result_update(result_id):
    return SimpleNamespace(
        message=None,
        edited_message=None,
        callback_query=None,
        chosen_inline_result=SimpleNamespace(result_id=result_id),
        inline_query=None,
    )


def _make_inline_query_update():
    return SimpleNamespace(
        message=None,
        edited_message=None,
        callback_query=None,
        chosen_inline_result=None,
        inline_query=SimpleNamespace(query=''),
    )


class TestKeyExtraction:
    """AC-11: _key_for_update returns correct (chat_id, thread_id) tuple."""

    def setup_method(self):
        self.proc = UnoUpdateProcessor(max_concurrent_updates=8)

    def test_message_in_normal_group_returns_chat_none(self):
        update = _make_message_update(chat_id=123)
        assert self.proc._key_for_update(update) == (123, None)

    def test_message_in_topic_returns_chat_thread(self):
        update = _make_message_update(chat_id=123, thread_id=42)
        assert self.proc._key_for_update(update) == (123, 42)

    def test_callback_query_returns_chat_thread(self):
        update = _make_callback_update(chat_id=999, thread_id=7)
        assert self.proc._key_for_update(update) == (999, 7)

    def test_chosen_inline_result_extracts_chat_thread_from_result_id(self):
        # Format: <game_id>:<base_id>:<anti_cheat>
        # We don't decode chat/thread directly — we look it up via game registry.
        # The processor accepts a resolver callback for that purpose.
        resolver = MagicMock(return_value=(555, 3))
        proc = UnoUpdateProcessor(max_concurrent_updates=8, game_resolver=resolver)
        update = _make_chosen_inline_result_update(result_id='abc123:r_5:0')
        assert proc._key_for_update(update) == (555, 3)
        resolver.assert_called_once_with('abc123')

    def test_chosen_inline_result_unknown_game_returns_none(self):
        resolver = MagicMock(return_value=None)
        proc = UnoUpdateProcessor(max_concurrent_updates=8, game_resolver=resolver)
        update = _make_chosen_inline_result_update(result_id='deadbe:r_5:0')
        assert proc._key_for_update(update) is None

    def test_chosen_inline_result_pseudo_game_id_returns_none(self):
        resolver = MagicMock()
        proc = UnoUpdateProcessor(max_concurrent_updates=8, game_resolver=resolver)
        update = _make_chosen_inline_result_update(result_id='none:hand:0')
        assert proc._key_for_update(update) is None
        resolver.assert_not_called()

    def test_inline_query_returns_none(self):
        update = _make_inline_query_update()
        assert self.proc._key_for_update(update) is None

    def test_malformed_result_id_returns_none(self):
        proc = UnoUpdateProcessor(max_concurrent_updates=8, game_resolver=MagicMock())
        update = _make_chosen_inline_result_update(result_id='garbage')
        assert proc._key_for_update(update) is None


class TestSerialization:
    """AC-12, AC-17: same key -> serial; different keys -> parallel."""

    def setup_method(self):
        self.proc = UnoUpdateProcessor(max_concurrent_updates=8)

    @pytest.mark.asyncio
    async def test_same_key_updates_run_serially(self):
        running = []
        peak_concurrent = [0]

        async def coro():
            running.append(1)
            peak_concurrent[0] = max(peak_concurrent[0], len(running))
            await asyncio.sleep(0.05)
            running.pop()

        update1 = _make_message_update(chat_id=1)
        update2 = _make_message_update(chat_id=1)

        await self.proc.initialize()
        try:
            await asyncio.gather(
                self.proc.do_process_update(update1, coro()),
                self.proc.do_process_update(update2, coro()),
            )
        finally:
            await self.proc.shutdown()

        assert peak_concurrent[0] == 1, "same-key updates must serialize"

    @pytest.mark.asyncio
    async def test_different_keys_run_in_parallel(self):
        running = []
        peak_concurrent = [0]

        async def coro():
            running.append(1)
            peak_concurrent[0] = max(peak_concurrent[0], len(running))
            await asyncio.sleep(0.05)
            running.pop()

        update1 = _make_message_update(chat_id=1)
        update2 = _make_message_update(chat_id=2)
        update3 = _make_message_update(chat_id=1, thread_id=7)

        await self.proc.initialize()
        try:
            await asyncio.gather(
                self.proc.do_process_update(update1, coro()),
                self.proc.do_process_update(update2, coro()),
                self.proc.do_process_update(update3, coro()),
            )
        finally:
            await self.proc.shutdown()

        assert peak_concurrent[0] == 3, "different keys must run in parallel"

    @pytest.mark.asyncio
    async def test_unkeyed_update_runs_without_lock(self):
        # AC-14: inline queries must never block on a per-chat lock
        running_inline = []
        peak_inline = [0]

        async def inline_coro():
            running_inline.append(1)
            peak_inline[0] = max(peak_inline[0], len(running_inline))
            await asyncio.sleep(0.05)
            running_inline.pop()

        update_a = _make_inline_query_update()
        update_b = _make_inline_query_update()
        update_c = _make_inline_query_update()

        await self.proc.initialize()
        try:
            await asyncio.gather(
                self.proc.do_process_update(update_a, inline_coro()),
                self.proc.do_process_update(update_b, inline_coro()),
                self.proc.do_process_update(update_c, inline_coro()),
            )
        finally:
            await self.proc.shutdown()

        assert peak_inline[0] == 3, "inline queries must never serialize"


class TestLifecycle:
    """AC-10: initialize/shutdown succeed without errors."""

    @pytest.mark.asyncio
    async def test_initialize_and_shutdown_are_noop_safe(self):
        proc = UnoUpdateProcessor(max_concurrent_updates=4)
        await proc.initialize()
        await proc.shutdown()

    def test_release_key_removes_lock(self):
        proc = UnoUpdateProcessor(max_concurrent_updates=4)
        # populate via a sync access to lock dict
        proc._lock_for_key((1, None))
        assert (1, None) in proc._locks
        proc.release_key((1, None))
        assert (1, None) not in proc._locks

    def test_release_unknown_key_is_noop(self):
        proc = UnoUpdateProcessor(max_concurrent_updates=4)
        proc.release_key((999, None))  # must not raise
