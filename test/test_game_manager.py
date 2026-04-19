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


import unittest

from telegram import User, Chat

from game_manager import GameManager
from errors import (AlreadyJoinedError, GameAlreadyRunningError,
                    LobbyClosedError, NoGameInChatError, NotEnoughPlayersError)


class Test(unittest.TestCase):
    """Tests for the singleton (chat_id, thread_id) -> Game model."""

    def setUp(self):
        self.gm = GameManager()

        self.chat0 = Chat(0, 'group')
        self.chat1 = Chat(1, 'group')
        self.chat2 = Chat(2, 'group')

        self.user0 = User(0, 'user0', is_bot=False)
        self.user1 = User(1, 'user1', is_bot=False)
        self.user2 = User(2, 'user2', is_bot=False)

    # AC-3, AC-4: chatid_games is a (chat_id, thread_id) -> Game dict
    def test_new_game_stores_singleton_per_chat_topic(self):
        g0 = self.gm.new_game(self.chat0)
        g1 = self.gm.new_game(self.chat1)

        self.assertIs(self.gm.chatid_games[(0, None)], g0)
        self.assertIs(self.gm.chatid_games[(1, None)], g1)

    # AC-1, AC-2: second new_game in the same (chat, topic) with a joined
    # player raises. An empty stale lobby may be silently replaced (UX parity
    # with the previous "remove old games without players" behaviour).
    def test_new_game_raises_when_topic_has_active_lobby(self):
        self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        with self.assertRaises(GameAlreadyRunningError):
            self.gm.new_game(self.chat0)

    def test_new_game_replaces_empty_stale_lobby(self):
        first = self.gm.new_game(self.chat0)
        second = self.gm.new_game(self.chat0)
        self.assertIsNot(first, second)
        self.assertIs(self.gm.chatid_games[(0, None)], second)
        self.assertNotIn(first.id, self.gm.games_by_id)

    # AC-1: same chat but different topics is allowed
    def test_new_game_allows_separate_topics_in_same_chat(self):
        g_main = self.gm.new_game(self.chat0)
        g_topic = self.gm.new_game(self.chat0, thread_id=42)

        self.assertIs(self.gm.chatid_games[(0, None)], g_main)
        self.assertIs(self.gm.chatid_games[(0, 42)], g_topic)
        self.assertIsNot(g_main, g_topic)
        self.assertEqual(g_topic.thread_id, 42)

    def test_game_for_chat_topic_returns_correct_game(self):
        g_main = self.gm.new_game(self.chat0)
        g_topic = self.gm.new_game(self.chat0, thread_id=7)

        self.assertIs(self.gm.game_for_chat_topic(0, None), g_main)
        self.assertIs(self.gm.game_for_chat_topic(0, 7), g_topic)
        self.assertIsNone(self.gm.game_for_chat_topic(0, 999))
        self.assertIsNone(self.gm.game_for_chat_topic(99, None))

    # AC-7: game_by_id resolves the game from a result_id prefix
    def test_game_by_id_resolves_game(self):
        g = self.gm.new_game(self.chat0)
        self.assertIs(self.gm.game_by_id(g.id), g)
        self.assertIsNone(self.gm.game_by_id('does-not-exist'))

    # Joining still works through the (chat, topic) lookup
    def test_join_game(self):
        self.assertRaises(NoGameInChatError,
                          self.gm.join_game,
                          *(self.user0, self.chat0))

        g0 = self.gm.new_game(self.chat0)

        self.gm.join_game(self.user0, self.chat0)
        self.assertEqual(len(g0.players), 1)

        self.gm.join_game(self.user1, self.chat0)
        self.assertEqual(len(g0.players), 2)

        g0.open = False
        self.assertRaises(LobbyClosedError,
                          self.gm.join_game,
                          *(self.user2, self.chat0))

        g0.open = True
        self.assertRaises(AlreadyJoinedError,
                          self.gm.join_game,
                          *(self.user1, self.chat0))

    def test_leave_game(self):
        self.gm.new_game(self.chat0)

        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)

        self.assertRaises(NotEnoughPlayersError,
                          self.gm.leave_game,
                          *(self.user1, self.chat0))

        self.gm.join_game(self.user2, self.chat0)
        self.gm.leave_game(self.user0, self.chat0)

        self.assertRaises(NoGameInChatError,
                          self.gm.leave_game,
                          *(self.user0, self.chat0))

    def test_end_game_clears_singleton(self):
        self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)

        self.assertEqual(len(self.gm.userid_players[0]), 1)

        self.gm.end_game(self.chat0, self.user0)
        self.assertNotIn((0, None), self.gm.chatid_games)
        self.assertNotIn(0, self.gm.userid_players)
        self.assertNotIn(1, self.gm.userid_players)

    def test_end_game_releases_processor_lock_when_registered(self):
        """end_game should call processor.release_key for cleanup."""
        released = []

        class FakeProcessor:
            def release_key(self, key):
                released.append(key)

        self.gm.update_processor = FakeProcessor()

        g = self.gm.new_game(self.chat0, thread_id=11)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)
        self.gm.end_game(self.chat0, self.user0)

        self.assertEqual(released, [(0, 11)])

    def test_end_game_without_processor_does_not_crash(self):
        # GameManager is still usable in test contexts without a processor
        self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)
        # Should not raise even though update_processor is None
        self.gm.end_game(self.chat0, self.user0)
