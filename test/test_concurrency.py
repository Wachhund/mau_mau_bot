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
import pytest

from game import Game
from game_manager import GameManager
from player import Player


class TestGameLock:
    """Tests that Game.lock serializes concurrent state mutations"""

    def setup_method(self):
        self.game = Game(None)
        p0 = Player(self.game, "Player 0")
        p1 = Player(self.game, "Player 1")
        p2 = Player(self.game, "Player 2")
        self.game.start()

    @pytest.mark.asyncio
    async def test_concurrent_turns_are_serialized(self):
        """Two concurrent turn() calls should advance by exactly 2 positions"""
        initial_player = self.game.current_player

        async def turn_with_lock(ready_event):
            ready_event.set()
            async with self.game.lock:
                self.game.turn()

        ready1 = asyncio.Event()
        ready2 = asyncio.Event()

        task1 = asyncio.create_task(turn_with_lock(ready1))
        task2 = asyncio.create_task(turn_with_lock(ready2))

        await asyncio.gather(task1, task2)

        # After two serialized turns, we should be 2 positions ahead
        expected = initial_player.next.next
        assert self.game.current_player == expected

    @pytest.mark.asyncio
    async def test_lock_is_per_game_instance(self):
        """Different games should have independent locks"""
        game2 = Game(None)
        Player(game2, "Player A")
        Player(game2, "Player B")
        game2.start()

        assert self.game.lock is not game2.lock

        # Both locks can be acquired concurrently without deadlock
        async with self.game.lock:
            async with game2.lock:
                self.game.turn()
                game2.turn()


class TestChatLock:
    """Tests that GameManager.chat_locks provides per-chat locking"""

    def setup_method(self):
        self.gm = GameManager()

    def test_same_chat_returns_same_lock(self):
        lock1 = self.gm.get_chat_lock(123)
        lock2 = self.gm.get_chat_lock(123)
        assert lock1 is lock2

    def test_different_chats_return_different_locks(self):
        lock1 = self.gm.get_chat_lock(123)
        lock2 = self.gm.get_chat_lock(456)
        assert lock1 is not lock2

    def test_lock_is_asyncio_lock(self):
        lock = self.gm.get_chat_lock(789)
        assert isinstance(lock, asyncio.Lock)
