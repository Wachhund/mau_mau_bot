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


"""A member leaving the group is removed from every game in the chat, each
game under its own lock."""

import asyncio
from types import SimpleNamespace

import pytest
from telegram import Chat, User

import bot
from shared_vars import gm, update_processor


class FakeBot:
    def __init__(self, on_send=None):
        self.sent = []          # (chat_id, text, message_thread_id)
        self.on_send = on_send

    async def send_message(self, chat_id, text=None, **kwargs):
        self.sent.append((chat_id, text, kwargs.get('message_thread_id')))
        if self.on_send is not None:
            await self.on_send(len(self.sent))
        await asyncio.sleep(0)


class FakeJob:
    def schedule_removal(self):
        pass


class FakeJobQueue:
    def __init__(self):
        self.scheduled = []

    def run_once(self, callback, when, data=None, **kwargs):
        self.scheduled.append((callback, when, data))
        return FakeJob()


def _context(fake_bot=None):
    return SimpleNamespace(bot=fake_bot or FakeBot(), job_queue=FakeJobQueue())


def _left_update(chat, user):
    msg = SimpleNamespace(chat=chat, left_chat_member=user, from_user=user,
                          message_thread_id=None, is_topic_message=False)
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_chat=chat, effective_user=user,
                           callback_query=None, chosen_inline_result=None,
                           inline_query=None)


def _user(user_id):
    return User(user_id, f'user{user_id}', is_bot=False)


def _player_ids(game):
    return {p.user.id for p in game.players}


@pytest.fixture(autouse=True)
def clean_game_manager():
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current):
        index.clear()
    yield
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current):
        index.clear()


CHAT = Chat(10, 'supergroup', title='Group')
LEAVER = _user(1)


def _game(thread_id, *users, mode='classic'):
    game = gm.new_game(CHAT, thread_id=thread_id)
    game.mode = mode
    for user in users:
        gm.join_game(user, CHAT, thread_id=thread_id)
    return game


@pytest.mark.asyncio
async def test_user_is_removed_from_every_topic_game():
    g_main = _game(None, LEAVER, _user(2), _user(3))
    g_topic = _game(7, LEAVER, _user(4), _user(5))
    fake_bot = FakeBot()

    await bot.status_update(_left_update(CHAT, LEAVER), _context(fake_bot))

    assert LEAVER.id not in _player_ids(g_main)
    assert LEAVER.id not in _player_ids(g_topic)
    assert LEAVER.id not in gm.userid_players
    assert [thread for _, _, thread in fake_bot.sent] == [None, 7]
    assert all('Removing' in text for _, text, _ in fake_bot.sent)


@pytest.mark.asyncio
async def test_games_the_user_is_not_in_are_left_alone():
    _game(None, LEAVER, _user(2), _user(3))
    other = _game(7, _user(4), _user(5), _user(6))
    fake_bot = FakeBot()

    await bot.status_update(_left_update(CHAT, LEAVER), _context(fake_bot))

    assert _player_ids(other) == {4, 5, 6}
    assert [thread for _, _, thread in fake_bot.sent] == [None]


@pytest.mark.asyncio
async def test_too_few_players_left_ends_the_game():
    game = _game(None, LEAVER, _user(2))
    fake_bot = FakeBot()

    await bot.status_update(_left_update(CHAT, LEAVER), _context(fake_bot))

    assert gm.game_for_chat_topic(CHAT.id, None) is None
    assert gm.game_by_id(game.id) is None
    assert fake_bot.sent[0][1] == 'Game ended!'


@pytest.mark.asyncio
async def test_departure_waits_for_a_handler_running_in_that_topic():
    g_topic = _game(7, LEAVER, _user(2), _user(3))
    events = []

    async def topic_handler():
        async with update_processor.serialized((CHAT.id, 7)):
            events.append('enter')
            await asyncio.sleep(0.05)
            events.append('release')

    async def departure():
        await asyncio.sleep(0)  # let the handler take the lock first
        await bot.status_update(_left_update(CHAT, LEAVER), _context())
        events.append('departure-done')

    await asyncio.gather(topic_handler(), departure())

    assert events == ['enter', 'release', 'departure-done']
    assert LEAVER.id not in _player_ids(g_topic)


@pytest.mark.asyncio
async def test_game_ending_during_an_earlier_announcement_is_skipped():
    """Three topic games; the middle one ends and is replaced while the first
    topic's announcement is being sent. The replacement must be untouched and
    the third game still cleaned up."""
    g_main = _game(None, LEAVER, _user(2), _user(3))
    g_middle = _game(7, LEAVER, _user(4), _user(5))
    g_last = _game(8, LEAVER, _user(6), _user(7))
    replacement = {}

    async def end_middle_game(sent_count):
        if sent_count == 1:
            gm.end_game(g_middle)
            replacement['game'] = _game(7, _user(4), _user(5), _user(8))

    fake_bot = FakeBot(on_send=end_middle_game)

    await bot.status_update(_left_update(CHAT, LEAVER), _context(fake_bot))

    assert LEAVER.id not in _player_ids(g_main)
    assert LEAVER.id not in _player_ids(g_last)
    assert gm.game_for_chat_topic(CHAT.id, 7) is replacement['game']
    assert _player_ids(replacement['game']) == {4, 5, 8}
    assert [thread for _, _, thread in fake_bot.sent] == [None, 8]


@pytest.mark.asyncio
async def test_countdown_is_rearmed_only_when_the_current_player_leaves():
    game = _game(None, _user(1), _user(2), _user(3), _user(4), mode='fast')
    game.start()  # plays the first card, which may already advance the turn
    for player in game.players:
        player.draw_first_hand()
    current = game.current_player.user

    context = _context()
    await bot.status_update(_left_update(CHAT, current), context)

    assert len(context.job_queue.scheduled) == 1
    assert game.current_player.user.id != current.id

    # A non-current player leaving must not touch the timer.
    bystander = next(p.user for p in game.players
                     if p is not game.current_player)
    context = _context()
    await bot.status_update(_left_update(CHAT, bystander), context)
    assert context.job_queue.scheduled == []


@pytest.mark.asyncio
async def test_no_countdown_for_an_unstarted_lobby():
    _game(None, LEAVER, _user(2), _user(3), mode='fast')
    context = _context()

    await bot.status_update(_left_update(CHAT, LEAVER), context)

    assert context.job_queue.scheduled == []
