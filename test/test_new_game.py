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


"""/new over an existing game: lobbies and idle games give way, running
games only for the creator or an admin."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from telegram import Chat, User

import bot
import utils
from shared_vars import gm


CHAT = Chat(40, 'supergroup', title='Group')


class FakeBot:
    def __init__(self, admins=()):
        self.sent = []
        self.admins = admins

    async def send_message(self, chat_id, text=None, **kwargs):
        self.sent.append((chat_id, text))
        await asyncio.sleep(0)

    async def get_chat_administrators(self, chat_id):
        return [SimpleNamespace(user=user) for user in self.admins]


def _context(admins=()):
    return SimpleNamespace(bot=FakeBot(admins), job_queue=None, args=[])


def _new_update(user):
    msg = SimpleNamespace(chat=CHAT, from_user=user, message_id=1,
                          message_thread_id=None, is_topic_message=False,
                          left_chat_member=None, reply_to_message=None)
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_chat=CHAT, effective_user=user,
                           callback_query=None, chosen_inline_result=None,
                           inline_query=None)


def _user(user_id):
    return User(user_id, f'user{user_id}', is_bot=False)


CREATOR = _user(1)
STRANGER = _user(3)
ADMIN = _user(4)


@pytest.fixture(autouse=True)
def clean_state():
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current, gm.remind_dict, utils._admin_cache):
        index.clear()
    yield
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current, gm.remind_dict, utils._admin_cache):
        index.clear()


def _lobby():
    game = gm.new_game(CHAT)
    game.mode = 'classic'
    game.owner.append(CREATOR.id)
    gm.join_game(CREATOR, CHAT)
    gm.join_game(_user(2), CHAT)
    return game


def _running_game(idle_seconds=0):
    game = _lobby()
    game.start()
    for player in game.players:
        player.draw_first_hand()
    game.last_activity = datetime.now() - timedelta(seconds=idle_seconds)
    return game


def _texts(context):
    return [text for _, text in context.bot.sent]


@pytest.mark.asyncio
async def test_anyone_replaces_a_lobby_that_has_not_started():
    old = _lobby()
    context = _context()

    await bot.new_game(_new_update(STRANGER), context)

    new = gm.game_for_chat_topic(CHAT.id, None)
    assert new is not old
    assert gm.game_by_id(old.id) is None
    assert new.owner == [STRANGER.id] or STRANGER.id in new.owner
    assert _texts(context)[0] == 'Game ended!'
    assert _texts(context)[1].startswith('Created a new game!')


@pytest.mark.asyncio
async def test_running_game_is_refused_for_a_stranger():
    old = _running_game()
    context = _context()

    await bot.new_game(_new_update(STRANGER), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is old
    assert 'already a game' in _texts(context)[0]


@pytest.mark.asyncio
async def test_idle_running_game_gives_way_to_a_stranger():
    old = _running_game(idle_seconds=bot.STALE_GAME_TIMEOUT + 1)
    context = _context()

    await bot.new_game(_new_update(STRANGER), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is not old
    assert _texts(context)[0] == 'Game ended!'


@pytest.mark.asyncio
async def test_creator_replaces_a_running_game_at_once():
    old = _running_game()
    context = _context()

    await bot.new_game(_new_update(CREATOR), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is not old


@pytest.mark.asyncio
async def test_admin_replaces_a_running_game_at_once():
    old = _running_game()
    context = _context(admins=[ADMIN])

    await bot.new_game(_new_update(ADMIN), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is not old


@pytest.mark.asyncio
async def test_timeout_zero_turns_idle_replacement_off(monkeypatch):
    monkeypatch.setattr(bot, 'STALE_GAME_TIMEOUT', 0)
    old = _running_game(idle_seconds=24 * 3600)
    context = _context()

    await bot.new_game(_new_update(STRANGER), context)

    assert gm.game_for_chat_topic(CHAT.id, None) is old


@pytest.mark.asyncio
async def test_refused_new_keeps_the_reminder_subscriptions():
    _running_game()
    gm.remind_dict[CHAT.id] = {7, 8}
    context = _context()

    await bot.new_game(_new_update(STRANGER), context)
    await utils.drain_background_tasks()

    assert gm.remind_dict[CHAT.id] == {7, 8}
    assert all(chat_id == CHAT.id for chat_id, _ in context.bot.sent)


@pytest.mark.asyncio
async def test_successful_new_notifies_subscribers_in_the_background():
    gm.remind_dict[CHAT.id] = {7, 8}
    context = _context()

    await bot.new_game(_new_update(CREATOR), context)
    await utils.drain_background_tasks()

    assert CHAT.id not in gm.remind_dict
    notified = {chat_id for chat_id, text in context.bot.sent
                if text.startswith('A new game has been started')}
    assert notified == {7, 8}


def test_turns_count_as_activity():
    game = _running_game(idle_seconds=1000)
    assert game.idle_seconds() >= 1000
    game.turn()
    assert game.idle_seconds() < 1
