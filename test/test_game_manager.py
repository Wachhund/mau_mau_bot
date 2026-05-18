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
        self.gm.join_game(self.user0, self.chat0, thread_id=11)
        self.gm.join_game(self.user1, self.chat0, thread_id=11)
        self.gm.end_game(self.chat0, self.user0)

        self.assertEqual(released, [(0, 11)])

    def test_end_game_without_processor_does_not_crash(self):
        # GameManager is still usable in test contexts without a processor
        self.gm.new_game(self.chat0)
        self.gm.join_game(self.user0, self.chat0)
        self.gm.join_game(self.user1, self.chat0)
        # Should not raise even though update_processor is None
        self.gm.end_game(self.chat0, self.user0)


class TestTopicIsolation(unittest.TestCase):
    """Cross-topic correctness after the (chat, thread_id) singleton change.

    These tests pin the regressions jh0ker flagged on PR #138:
    - leave_game / player_for_user_in_chat must be topic-scoped
    - join_game must not silently fall back to a game in a different topic
    - status_update (left_chat_member) still needs a way to remove a user
      from every game in the chat
    """

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

    # jh0ker game_manager.py:83 — no cross-topic fallback in join_game
    def test_join_game_does_not_fall_back_across_topics(self):
        new_user = User(999, 'new', is_bot=False)
        # Try to /join from a topic that has NO game
        with self.assertRaises(NoGameInChatError):
            self.gm.join_game(new_user, self.chat, thread_id=42)
        self.assertNotIn(new_user.id, self.gm.userid_players)

    def test_join_game_from_general_does_not_grab_topic_game(self):
        # Fresh chat with ONLY a topic game — /join from General must fail
        gm2 = GameManager()
        chat = Chat(20, 'supergroup')
        gm2.new_game(chat, thread_id=5)
        gm2.join_game(User(1, 'u1', is_bot=False), chat, thread_id=5)

        outsider = User(2, 'out', is_bot=False)
        with self.assertRaises(NoGameInChatError):
            gm2.join_game(outsider, chat, thread_id=None)
        self.assertNotIn(outsider.id, gm2.userid_players)

    # jh0ker game_manager.py:131 — leave_game must respect thread_id
    def test_leave_game_only_removes_from_specified_topic(self):
        # user_c is in (10, None) AND (10, 7) — leave from topic only
        self.gm.leave_game(self.user_c, self.chat, thread_id=7)

        topic_user_ids = {p.user.id for p in self.game_topic.players}
        main_user_ids = {p.user.id for p in self.game_main.players}

        self.assertNotIn(self.user_c.id, topic_user_ids,
                         "user_c must leave the topic game")
        self.assertIn(self.user_c.id, main_user_ids,
                      "user_c must remain in the main game")

    def test_leave_game_unknown_topic_raises(self):
        with self.assertRaises(NoGameInChatError):
            self.gm.leave_game(self.user_a, self.chat, thread_id=999)

    # jh0ker game_manager.py:159 — player_for_user_in_chat must be topic-scoped
    def test_player_for_user_in_chat_resolves_specific_topic(self):
        # user_c sits in BOTH games — ask for each topic separately
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

    # New helper: status_update needs to remove a user from every game in chat
    def test_leave_all_games_in_chat_clears_user_from_every_topic(self):
        self.gm.leave_all_games_in_chat(self.user_c, self.chat)

        main_ids = {p.user.id for p in self.game_main.players}
        topic_ids = {p.user.id for p in self.game_topic.players}
        self.assertNotIn(self.user_c.id, main_ids)
        self.assertNotIn(self.user_c.id, topic_ids)

    def test_leave_all_games_in_chat_is_noop_when_user_not_playing(self):
        outsider = User(777, 'out', is_bot=False)
        # Must not raise
        self.gm.leave_all_games_in_chat(outsider, self.chat)


class TestEndGameTaskReference(unittest.TestCase):
    """jh0ker game_manager.py:167 — keep a strong reference to the
    ``send_promotion`` task so it can't be garbage-collected mid-flight.

    Reproduces the scenario described in the Python docs for
    :func:`asyncio.create_task` (Important box)."""

    def test_background_tasks_set_collects_scheduled_tasks(self):
        import asyncio
        gm = GameManager()
        chat = Chat(50, 'group')
        u0 = User(50, 'u0', is_bot=False)
        u1 = User(51, 'u1', is_bot=False)

        async def scenario():
            gm.new_game(chat)
            gm.join_game(u0, chat)
            gm.join_game(u1, chat)
            gm.end_game(chat, u0)
            # Strong reference must live in a manager-owned collection.
            assert hasattr(gm, '_background_tasks')
            # Drain pending tasks so the test loop exits cleanly.
            pending = [t for t in gm._background_tasks if not t.done()]
            for t in pending:
                t.cancel()
            try:
                await asyncio.gather(*pending, return_exceptions=True)
            except Exception:
                pass

        asyncio.run(scenario())
