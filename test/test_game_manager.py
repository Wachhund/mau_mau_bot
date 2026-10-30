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
    """One game per (chat_id, thread_id)."""

    def setUp(self):
        self.gm = GameManager()

        self.chat0 = Chat(0, 'group')
        self.chat1 = Chat(1, 'group')
        self.chat2 = Chat(2, 'group')

        self.user0 = User(0, 'user0', is_bot=False)
        self.user1 = User(1, 'user1', is_bot=False)
        self.user2 = User(2, 'user2', is_bot=False)

    def test_new_game_stores_singleton_per_chat_topic(self):
        g0 = self.gm.new_game(self.chat0)
        g1 = self.gm.new_game(self.chat1)

        self.assertIs(self.gm.game_for_chat_topic(0, None), g0)
        self.assertIs(self.gm.game_for_chat_topic(1, None), g1)

    def test_new_game_raises_when_topic_has_active_lobby(self):
        self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        with self.assertRaises(GameAlreadyRunningError):
            self.gm.new_game(self.chat0)

    def test_new_game_replaces_empty_stale_lobby(self):
        first = self.gm.new_game(self.chat0)
        second = self.gm.new_game(self.chat0)
        self.assertIsNot(first, second)
        self.assertIs(self.gm.game_for_chat_topic(0, None), second)
        self.assertIsNone(self.gm.game_by_id(first.id))

    def test_new_game_allows_separate_topics_in_same_chat(self):
        g_main = self.gm.new_game(self.chat0)
        g_topic = self.gm.new_game(self.chat0, thread_id=42)

        self.assertIs(self.gm.game_for_chat_topic(0, None), g_main)
        self.assertIs(self.gm.game_for_chat_topic(0, 42), g_topic)
        self.assertIsNot(g_main, g_topic)
        self.assertEqual(g_topic.thread_id, 42)

    def test_game_for_chat_topic_returns_correct_game(self):
        g_main = self.gm.new_game(self.chat0)
        g_topic = self.gm.new_game(self.chat0, thread_id=7)

        self.assertIs(self.gm.game_for_chat_topic(0, None), g_main)
        self.assertIs(self.gm.game_for_chat_topic(0, 7), g_topic)
        self.assertIsNone(self.gm.game_for_chat_topic(0, 999))
        self.assertIsNone(self.gm.game_for_chat_topic(99, None))

    def test_games_in_chat_lists_every_topic_of_that_chat_only(self):
        g_main = self.gm.new_game(self.chat0)
        g_topic = self.gm.new_game(self.chat0, thread_id=7)
        self.gm.new_game(self.chat1)

        self.assertCountEqual(self.gm.games_in_chat(0), [g_main, g_topic])
        self.assertEqual(self.gm.games_in_chat(99), [])

    def test_game_by_id_resolves_game(self):
        g = self.gm.new_game(self.chat0)
        self.assertIs(self.gm.game_by_id(g.id), g)
        self.assertIsNone(self.gm.game_by_id('does-not-exist'))

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

    def test_join_with_an_exhausted_deck_leaves_no_trace(self):
        from errors import DeckEmptyError
        game = self.gm.new_game(self.chat0)
        game.mode = 'classic'
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)
        game.start()
        for player in game.players:
            player.draw_first_hand()
        game.deck.cards = game.deck.cards[:3]
        game.deck.graveyard = []

        with self.assertRaises(DeckEmptyError):
            self.gm.join_game(self.user2, self.chat0)

        self.assertEqual(len(game.players), 2)
        self.assertNotIn(self.user2.id, self.gm.userid_players)
        # The three cards that were dealt are back exactly once.
        self.assertEqual(len(game.deck.graveyard), 3)

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
        self.assertNotIn(self.user0.id, self.gm.userid_players)
        self.assertNotIn(self.user0.id, self.gm.userid_current)

    def test_end_game_clears_game_and_players(self):
        game = self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)

        self.assertEqual(len(self.gm.userid_players[0]), 1)

        self.gm.end_game(game)
        self.assertIsNone(self.gm.game_for_chat_topic(0, None))
        self.assertIsNone(self.gm.game_by_id(game.id))
        self.assertNotIn(0, self.gm.chatid_games)
        self.assertNotIn(0, self.gm.userid_players)
        self.assertNotIn(1, self.gm.userid_players)
        self.assertNotIn(0, self.gm.userid_current)

    def test_end_game_only_affects_its_topic(self):
        g_main = self.gm.new_game(self.chat0)
        g_topic = self.gm.new_game(self.chat0, thread_id=7)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)
        self.gm.join_game(self.user0, self.chat0, thread_id=7)
        self.gm.join_game(self.user2, self.chat0, thread_id=7)

        self.gm.end_game(g_topic)

        self.assertIs(self.gm.game_for_chat_topic(0, None), g_main)
        self.assertIsNone(self.gm.game_for_chat_topic(0, 7))
        self.assertEqual(len(self.gm.userid_players[0]), 1)
        self.assertIs(self.gm.userid_current[0].game, g_main)
        self.assertNotIn(2, self.gm.userid_players)

    def test_end_game_keeps_current_selection_of_other_game(self):
        g_main = self.gm.new_game(self.chat0)
        g_other = self.gm.new_game(self.chat1)
        self.gm.join_game(self.user0, self.chat1)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.userid_current[0] = self.gm.player_for_user_in_chat(
            self.user0, self.chat1)

        self.gm.end_game(g_main)

        self.assertIs(self.gm.userid_current[0].game, g_other)

    def test_end_game_twice_is_harmless(self):
        game = self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.end_game(game)
        self.gm.end_game(game)
        self.assertNotIn(0, self.gm.chatid_games)

    def test_end_game_does_not_remove_a_replacement_game(self):
        old = self.gm.new_game(self.chat0)
        new = self.gm.new_game(self.chat0)
        self.gm.end_game(old)
        self.assertIs(self.gm.game_for_chat_topic(0, None), new)

class TestTopicIsolation(unittest.TestCase):
    """Cross-topic correctness of the (chat, thread_id) singleton model."""

    def setUp(self):
        self.gm = GameManager()
        self.chat = Chat(10, 'supergroup')

        self.user_a = User(100, 'a', is_bot=False)
        self.user_b = User(101, 'b', is_bot=False)
        self.user_c = User(102, 'c', is_bot=False)
        self.user_d = User(103, 'd', is_bot=False)
        self.user_e = User(104, 'e', is_bot=False)

        # Two parallel games in the same chat, different topics
        self.game_main = self.gm.new_game(self.chat)               # (10, None)
        self.game_topic = self.gm.new_game(self.chat, thread_id=7) # (10, 7)

        # 3 players in each so leave does not trigger NotEnoughPlayersError
        self.gm.join_game(self.user_a, self.chat, thread_id=None)
        self.gm.join_game(self.user_d, self.chat, thread_id=None)
        self.gm.join_game(self.user_c, self.chat, thread_id=None)

        self.gm.join_game(self.user_b, self.chat, thread_id=7)
        self.gm.join_game(self.user_e, self.chat, thread_id=7)
        self.gm.join_game(self.user_c, self.chat, thread_id=7)
        # user_c is now in both games; currently active = topic (last join)

    def test_join_game_does_not_fall_back_across_topics(self):
        new_user = User(999, 'new', is_bot=False)
        with self.assertRaises(NoGameInChatError):
            self.gm.join_game(new_user, self.chat, thread_id=42)
        self.assertNotIn(new_user.id, self.gm.userid_players)

    def test_join_game_from_general_does_not_grab_topic_game(self):
        gm2 = GameManager()
        chat = Chat(20, 'supergroup')
        gm2.new_game(chat, thread_id=5)
        gm2.join_game(User(1, 'u1', is_bot=False), chat, thread_id=5)

        outsider = User(2, 'out', is_bot=False)
        with self.assertRaises(NoGameInChatError):
            gm2.join_game(outsider, chat, thread_id=None)
        self.assertNotIn(outsider.id, gm2.userid_players)

    def test_leave_game_only_removes_from_specified_topic(self):
        self.gm.leave_game(self.user_c, self.chat, thread_id=7)

        topic_user_ids = {p.user.id for p in self.game_topic.players}
        main_user_ids = {p.user.id for p in self.game_main.players}

        self.assertNotIn(self.user_c.id, topic_user_ids)
        self.assertIn(self.user_c.id, main_user_ids)
        self.assertIs(self.gm.userid_current[self.user_c.id].game,
                      self.game_main)

    def test_leave_game_unknown_topic_raises(self):
        with self.assertRaises(NoGameInChatError):
            self.gm.leave_game(self.user_a, self.chat, thread_id=999)

    def test_player_for_user_in_chat_resolves_specific_topic(self):
        p_main = self.gm.player_for_user_in_chat(self.user_c, self.chat,
                                                 thread_id=None)
        p_topic = self.gm.player_for_user_in_chat(self.user_c, self.chat,
                                                  thread_id=7)
        self.assertIsNotNone(p_main)
        self.assertIsNotNone(p_topic)
        self.assertIs(p_main.game, self.game_main)
        self.assertIs(p_topic.game, self.game_topic)
        self.assertIsNot(p_main, p_topic)

    def test_player_for_user_in_chat_unknown_topic_returns_none(self):
        self.assertIsNone(
            self.gm.player_for_user_in_chat(self.user_a, self.chat,
                                             thread_id=999))
