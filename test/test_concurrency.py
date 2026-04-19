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


"""After UNO-12 the per-Game lock and per-chat lock are gone — locking is
centralised in :class:`uno_update_processor.UnoUpdateProcessor`, which has its
own dedicated test suite. This file pins the *removal* so that nobody
accidentally re-introduces those locks via merge."""

from game import Game
from game_manager import GameManager
from player import Player


class TestLocksAreRemoved:
    """Per-Game and per-chat asyncio.Locks must not exist any more."""

    def test_game_has_no_lock_attribute(self):
        game = Game(None)
        Player(game, 'p0')
        Player(game, 'p1')
        Player(game, 'p2')
        assert not hasattr(game, 'lock'), \
            "Game.lock must be removed — locking lives in UnoUpdateProcessor"

    def test_game_manager_has_no_chat_locks(self):
        gm = GameManager()
        assert not hasattr(gm, 'chat_locks'), \
            "GameManager.chat_locks must be removed — UnoUpdateProcessor owns the locks"
        assert not hasattr(gm, 'get_chat_lock'), \
            "GameManager.get_chat_lock must be removed"
