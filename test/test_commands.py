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


"""Command handlers: /skip, /kill, /kick, /join and the game selection."""

import asyncio
from types import SimpleNamespace

import pytest
from telegram import Chat, User

import bot
import utils
from shared_vars import gm


CHAT = Chat(50, 'supergroup', title='Group')


class FakeBot:
    def __init__(self, admins=()):
        self.sent = []
        self.answered = []
        self.edited = []
        self.admins = admins

    async def send_message(self, chat_id, text=None, **kwargs):
        self.sent.append(text)
        await asyncio.sleep(0)

    async def get_chat_administrators(self, chat_id):
        return [SimpleNamespace(user=user) for user in self.admins]

    async def answer_callback_query(self, callback_query_id, text=None,
                                    show_alert=False, **kwargs):
        self.answered.append((text, show_alert))

    async def edit_message_text(self, chat_id=None, message_id=None,
                                text=None, **kwargs):
        self.edited.append(text)


class FakeJob:
    def schedule_removal(self):
        pass


class FakeJobQueue:
    def __init__(self):
        self.scheduled = []

    def run_once(self, callback, when, data=None, **kwargs):
        self.scheduled.append((callback, when, data))
        return FakeJob()


def _context(admins=()):
    return SimpleNamespace(bot=FakeBot(admins), job_queue=FakeJobQueue(),
                           args=[])


def _message_update(user, reply_to=None, thread_id=None,
                    is_topic_message=False):
    msg = SimpleNamespace(chat=CHAT, from_user=user, message_id=1,
                          message_thread_id=thread_id,
                          is_topic_message=is_topic_message,
                          left_chat_member=None, reply_to_message=reply_to)
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_chat=CHAT, effective_user=user,
                           callback_query=None, chosen_inline_result=None,
                           inline_query=None)


def _callback_update(user, data):
    private = SimpleNamespace(id=user.id, type='private')
    msg = SimpleNamespace(chat=private, chat_id=user.id, message_id=5,
                          message_thread_id=None, is_topic_message=False,
                          left_chat_member=None)
    query = SimpleNamespace(data=data, from_user=user, id='cb1', message=msg)
    return SimpleNamespace(message=None, effective_message=msg,
                           effective_chat=private, effective_user=user,
                           callback_query=query, chosen_inline_result=None,
                           inline_query=None)


def _user(user_id):
    return User(user_id, f'user{user_id}', is_bot=False)


CREATOR = _user(1)
ADMIN = _user(9)


@pytest.fixture(autouse=True)
def clean_state():
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current, utils._admin_cache):
        index.clear()
    yield
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current, utils._admin_cache):
        index.clear()


def _lobby(*users, mode='fast'):
    game = gm.new_game(CHAT)
    game.mode = mode
    game.starter = CREATOR
    game.owner.append(CREATOR.id)
    for user in (CREATOR, *users):
        gm.join_game(user, CHAT)
    return game


def _started(*users, mode='fast'):
    game = _lobby(*users, mode=mode)
    game.start()
    for player in game.players:
        player.draw_first_hand()
    return game


def _ids(game):
    return {p.user.id for p in game.players}


@pytest.mark.asyncio
async def test_skip_in_an_unstarted_lobby_is_refused_and_arms_no_timer():
    game = _lobby(_user(2))
    context = _context()

    await bot.skip_player(_message_update(CREATOR), context)

    assert 'not started' in context.bot.sent[0]
    assert context.job_queue.scheduled == []
    assert not game.started
    assert _ids(game) == {1, 2}


@pytest.mark.asyncio
async def test_current_player_may_skip_themselves_and_the_timer_is_rearmed():
    game = _started(_user(2), _user(3))
    current = game.current_player
    context = _context()

    await bot.skip_player(_message_update(current.user), context)

    assert game.current_player is not current
    assert 'reduced' in context.bot.sent[0]
    assert len(context.job_queue.scheduled) == 1


@pytest.mark.asyncio
async def test_admin_who_is_not_playing_can_kill_the_game():
    game = _started(_user(2), _user(3))
    context = _context(admins=[ADMIN])

    await bot.kill_game(_message_update(ADMIN), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is None
    assert gm.game_by_id(game.id) is None
    assert context.bot.sent == ['Game ended!']


@pytest.mark.asyncio
async def test_stranger_cannot_kill_the_game():
    game = _started(_user(2), _user(3))
    context = _context()

    await bot.kill_game(_message_update(_user(7)), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is game
    assert 'Only the game creator' in context.bot.sent[0]


@pytest.mark.asyncio
async def test_kick_removes_the_replied_to_player():
    game = _started(_user(2), _user(3), _user(4))
    victim = next(p.user for p in game.players
                  if p is not game.current_player)
    reply = SimpleNamespace(from_user=victim, forum_topic_created=None)
    context = _context()

    await bot.kick_player(_message_update(CREATOR, reply_to=reply), context)

    assert victim.id not in _ids(game)
    assert any('was kicked by' in text for text in context.bot.sent)


@pytest.mark.asyncio
async def test_kick_in_a_forum_topic_without_a_real_reply_kicks_nobody():
    """Telegram attaches the topic's creation message as reply_to_message to
    every plain message in a topic."""
    game = _started(_user(2), _user(3), _user(4))
    pseudo_reply = SimpleNamespace(from_user=_user(2),
                                   forum_topic_created=SimpleNamespace())
    context = _context()

    await bot.kick_player(_message_update(CREATOR, reply_to=pseudo_reply),
                          context)

    assert _ids(game) == {1, 2, 3, 4}
    assert 'Please reply' in context.bot.sent[0]


@pytest.mark.asyncio
async def test_join_sent_as_a_reply_in_a_normal_group_joins_the_game():
    game = _lobby()
    context = _context()

    # A reply carries the reply thread's id but is not a topic message.
    await bot.join_game(_message_update(_user(2), thread_id=555), context)

    assert _ids(game) == {1, 2}
    assert context.bot.sent == ['Joined the game']


@pytest.mark.asyncio
async def test_select_game_switches_the_current_game_by_id():
    user = _user(5)
    game_here = _lobby(user)
    other_chat = Chat(51, 'supergroup', title='Elsewhere')
    game_there = gm.new_game(other_chat, thread_id=7)
    gm.join_game(user, other_chat, thread_id=7)
    gm.userid_current[user.id] = gm.player_for_user_in_chat(user, CHAT)
    context = _context()

    await bot.select_game(_callback_update(user, game_there.id), context)

    assert gm.userid_current[user.id].game is game_there
    assert 'Elsewhere' in context.bot.edited[0]
    assert 'topic 7' in context.bot.edited[0]
    assert gm.userid_current[user.id].game is not game_here


@pytest.mark.asyncio
async def test_select_game_with_a_stale_id_answers_the_callback():
    user = _user(5)
    game_here = _lobby(user)
    context = _context()

    await bot.select_game(_callback_update(user, 'gone'), context)

    assert context.bot.answered == [('Game not found.', True)]
    assert context.bot.edited == []
    assert gm.userid_current[user.id].game is game_here
