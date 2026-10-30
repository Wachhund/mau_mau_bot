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


"""Skip timers act only on the turn they were armed for, and /start arms the
timer before it sends anything."""

import asyncio
from types import SimpleNamespace

import pytest
from telegram import Chat, User

import actions
import bot
import card as c
from shared_vars import gm


CHAT = Chat(30, 'supergroup', title='Group')


class FakeBot:
    def __init__(self, fail_sticker=False):
        self.sent = []
        self.stickers = []
        self.fail_sticker = fail_sticker

    async def send_message(self, chat_id, text=None, **kwargs):
        self.sent.append(text)
        await asyncio.sleep(0)

    async def send_sticker(self, chat_id, sticker=None, **kwargs):
        if self.fail_sticker:
            raise RuntimeError('network down')
        self.stickers.append(sticker)


class FakeJob:
    def __init__(self, callback, data):
        self.callback = callback
        self.data = data
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    def __init__(self):
        self.scheduled = []

    def run_once(self, callback, when, data=None, **kwargs):
        job = FakeJob(callback, data)
        self.scheduled.append(job)
        return job


def _context(fake_bot=None, job=None):
    return SimpleNamespace(bot=fake_bot or FakeBot(), job_queue=FakeJobQueue(),
                           job=job, args=[])


def _message_update(user):
    msg = SimpleNamespace(chat=CHAT, from_user=user, message_id=1,
                          message_thread_id=None, is_topic_message=False,
                          left_chat_member=None, reply_to_message=None)
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_chat=CHAT, effective_user=user,
                           callback_query=None, chosen_inline_result=None,
                           inline_query=None)


def _user(user_id):
    return User(user_id, f'user{user_id}', is_bot=False)


@pytest.fixture(autouse=True)
def clean_game_manager():
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current):
        index.clear()
    yield
    for index in (gm.chatid_games, gm.games_by_id, gm.userid_players,
                  gm.userid_current):
        index.clear()


def _fast_game(*users, started=True):
    game = gm.new_game(CHAT)
    game.mode = 'fast'
    for user in users:
        gm.join_game(user, CHAT)
    if started:
        game.start()
        for player in game.players:
            player.draw_first_hand()
        game.last_card = c.Card(c.RED, '5')
        game.draw_counter = 0
        game.choosing_color = False
    return game


async def _fire(job, fake_bot=None):
    """Run the job-queue callback the way PTB would."""
    context = _context(fake_bot, job=job)
    await actions.skip_job(context)
    return context


@pytest.mark.asyncio
async def test_timer_armed_for_an_earlier_turn_does_nothing():
    game = _fast_game(_user(1), _user(2), _user(3))
    queue = FakeJobQueue()
    actions.start_player_countdown(game, queue)
    stale_job = queue.scheduled[-1]

    # The player moves in time: the turn passes and a new timer is armed.
    game.turn()
    actions.start_player_countdown(game, queue)
    now_current = game.current_player
    cards_before = len(now_current.cards)

    context = await _fire(stale_job)

    assert game.current_player is now_current
    assert len(now_current.cards) == cards_before
    assert context.bot.sent == []


@pytest.mark.asyncio
async def test_live_timer_skips_the_current_player_and_rearms():
    game = _fast_game(_user(1), _user(2), _user(3))
    queue = FakeJobQueue()
    actions.start_player_countdown(game, queue)
    job = queue.scheduled[-1]
    current = game.current_player
    cards_before = len(current.cards)

    context = await _fire(job)

    assert game.current_player is not current
    assert len(current.cards) == cards_before + 1
    assert 'Next player' in context.bot.sent[0]
    assert len(queue.scheduled) == 2
    assert game.job is queue.scheduled[-1]


def test_timer_carries_the_locales_of_the_game_not_the_caller():
    from internationalization import locale_stack
    game = _fast_game(_user(1), _user(2), _user(3))
    queue = FakeJobQueue()

    with locale_stack(['de_DE']):
        actions.start_player_countdown(game, queue)

    # No player has a language setting, so the game speaks English.
    assert queue.scheduled[-1].data.locales == ['en_US']


@pytest.mark.asyncio
async def test_ending_a_game_cancels_its_timer():
    game = _fast_game(_user(1), _user(2), _user(3))
    queue = FakeJobQueue()
    actions.start_player_countdown(game, queue)
    job = queue.scheduled[-1]
    current = game.current_player
    cards_before = len(current.cards)

    gm.end_game(game)
    context = await _fire(job)

    assert job.removed
    assert len(current.cards) == cards_before
    assert context.bot.sent == []


@pytest.mark.asyncio
async def test_start_arms_the_timer_even_when_the_opening_sticker_fails():
    game = _fast_game(_user(1), _user(2), _user(3), started=False)
    context = _context(FakeBot(fail_sticker=True))

    await bot.start_game(_message_update(_user(1)), context)

    assert game.started
    assert len(context.job_queue.scheduled) == 1
    assert game.job is context.job_queue.scheduled[0]
    assert any('First player' in text for text in context.bot.sent)


@pytest.mark.asyncio
async def test_start_sends_the_opening_card():
    game = _fast_game(_user(1), _user(2), _user(3), started=False)
    context = _context()

    await bot.start_game(_message_update(_user(1)), context)

    assert context.bot.stickers == [c.STICKERS[str(game.last_card)]]


@pytest.mark.asyncio
async def test_leave_rearms_the_timer_only_for_the_current_player():
    game = _fast_game(_user(1), _user(2), _user(3), _user(4))
    current = game.current_player.user

    context = _context()
    await bot.leave_game(_message_update(current), context)
    assert len(context.job_queue.scheduled) == 1

    bystander = next(p.user for p in game.players
                     if p is not game.current_player)
    context = _context()
    await bot.leave_game(_message_update(bystander), context)
    assert context.job_queue.scheduled == []
