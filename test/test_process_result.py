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


"""Chosen inline results only act when they are a legal move right now."""

import asyncio
from types import SimpleNamespace

import pytest
from telegram import Chat, User

import bot
import card as c
from shared_vars import gm


CHAT = Chat(20, 'supergroup', title='Group')


class FakeBot:
    def __init__(self):
        self.sent = []
        self.answered = []

    async def send_message(self, chat_id, text=None, **kwargs):
        self.sent.append(text)
        await asyncio.sleep(0)

    async def answer_inline_query(self, inline_query_id, results, **kwargs):
        self.answered.append(results)


class FakeJob:
    def schedule_removal(self):
        pass


class FakeJobQueue:
    def __init__(self):
        self.scheduled = []

    def run_once(self, callback, when, data=None, **kwargs):
        self.scheduled.append((callback, when, data))
        return FakeJob()


def _context():
    return SimpleNamespace(bot=FakeBot(), job_queue=FakeJobQueue())


def _chosen(user, result_id):
    return SimpleNamespace(
        chosen_inline_result=SimpleNamespace(from_user=user, result_id=result_id),
        effective_user=user, effective_chat=None, effective_message=None,
        message=None, callback_query=None, inline_query=None)


def _inline_query(user):
    return SimpleNamespace(
        inline_query=SimpleNamespace(from_user=user, id='q1', query=''),
        effective_user=user, effective_chat=None, effective_message=None,
        message=None, callback_query=None, chosen_inline_result=None)


def _result(player, base_id):
    return f'{player.game.id}:{base_id}:{player.anti_cheat}'


async def _act(player, base_id, context=None):
    """Submit an inline result for ``player`` as the current list would encode it."""
    context = context or _context()
    await bot.process_result(_chosen(player.user, _result(player, base_id)),
                             context)
    return context


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


def _started_game(*users, mode='classic'):
    game = gm.new_game(CHAT)
    game.mode = mode
    for user in users:
        gm.join_game(user, CHAT)
    game.start()
    for player in game.players:
        player.draw_first_hand()
    # The first card may already have had an effect; start from a known state.
    game.last_card = c.Card(c.RED, '5')
    game.draw_counter = 0
    game.choosing_color = False
    return game


def _other_player(game):
    return next(p for p in game.players if p is not game.current_player)


@pytest.mark.asyncio
async def test_a_fresh_list_fetched_during_the_send_cannot_draw_again():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player
    before = len(current.cards)
    context = _context()

    first = bot.process_result(_chosen(current.user, _result(current, 'draw')),
                               context)

    async def second():
        await asyncio.sleep(0)  # the first move is now inside its send
        # An inline query answered in that window carries the new anti_cheat.
        await bot.process_result(
            _chosen(current.user, _result(current, 'draw')), context)

    await asyncio.gather(first, second())

    assert len(current.cards) == before + 1
    assert current.drew


@pytest.mark.asyncio
async def test_pass_needs_a_draw_first():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player

    await _act(current, 'pass')
    assert game.current_player is current

    await _act(current, 'draw')
    await _act(current, 'pass')
    assert game.current_player is not current


@pytest.mark.asyncio
async def test_non_current_player_cannot_play_a_card():
    game = _started_game(_user(1), _user(2), _user(3))
    other = _other_player(game)
    other.cards = [c.Card(c.RED, '7')]  # would match the last card
    anti_cheat, bluffing = other.anti_cheat, other.bluffing

    context = await _act(other, 'r_7')

    assert other.cards == [c.Card(c.RED, '7')]
    assert other.anti_cheat == anti_cheat
    assert other.bluffing is bluffing
    assert context.bot.sent == []


@pytest.mark.asyncio
async def test_colour_chooser_cannot_draw_pass_or_call_bluff():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player
    current.cards = [c.Card(None, None, c.DRAW_FOUR), c.Card(c.BLUE, '2')]

    await _act(current, c.DRAW_FOUR)
    assert game.choosing_color
    assert game.current_player is current

    for action in ('draw', 'pass', 'call_bluff'):
        before = len(current.cards)
        await _act(current, action)
        assert len(current.cards) == before
        assert game.choosing_color
        assert game.current_player is current


@pytest.mark.asyncio
async def test_next_player_cannot_draw_while_a_colour_choice_is_pending():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player
    current.cards = [c.Card(None, None, c.DRAW_FOUR), c.Card(c.BLUE, '2')]
    await _act(current, c.DRAW_FOUR)
    following = current.next
    before = len(following.cards)

    await _act(following, 'draw')

    assert len(following.cards) == before
    assert game.draw_counter == 4
    assert game.current_player is current


@pytest.mark.asyncio
async def test_card_that_is_not_playable_is_rejected_without_side_effects():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player
    current.cards = [c.Card(c.BLUE, '2'), c.Card(c.GREEN, '9')]
    anti_cheat, bluffing = current.anti_cheat, current.bluffing

    for base_id in ('b_2', 'g_9', 'r_5', 'not_a_card', 'r_5_x'):
        context = await _act(current, base_id)
        assert context.bot.sent == []

    assert current.cards == [c.Card(c.BLUE, '2'), c.Card(c.GREEN, '9')]
    assert current.anti_cheat == anti_cheat
    assert current.bluffing is bluffing
    assert game.current_player is current


@pytest.mark.asyncio
async def test_mode_change_only_by_the_creator_and_only_before_start():
    creator, other = _user(1), _user(2)
    game = gm.new_game(CHAT)
    game.mode = 'classic'
    game.owner.append(creator.id)
    gm.join_game(creator, CHAT)
    gm.join_game(other, CHAT)
    creator_player = gm.player_for_user_in_chat(creator, CHAT)
    other_player = gm.player_for_user_in_chat(other, CHAT)

    await _act(other_player, 'mode_wild')
    assert game.mode == 'classic'

    await _act(creator_player, 'mode_wild')
    assert game.mode == 'wild'

    game.start()
    await _act(creator_player, 'mode_fast')
    assert game.mode == 'wild'


@pytest.mark.asyncio
async def test_bluff_call_against_a_real_bluff_returns_the_cards():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player
    following = current.next
    # Holding red while playing a +4 on a red card is a bluff.
    current.cards = [c.Card(c.RED, '9'), c.Card(None, None, c.DRAW_FOUR),
                     c.Card(c.GREEN, '3')]

    await _act(current, c.DRAW_FOUR)
    assert current.bluffing is True

    await _act(current, c.BLUE)
    assert game.current_player is following
    assert game.last_card.color == c.BLUE

    before_current, before_following = len(current.cards), len(following.cards)
    context = await _act(following, 'call_bluff')

    assert len(current.cards) == before_current + 4
    assert len(following.cards) == before_following
    assert game.draw_counter == 0
    assert game.current_player is following.next
    assert context.bot.sent[0].startswith('Bluff called!')


def test_chosen_result_is_attributed_to_the_game_in_its_result_id():
    """Locales come from the game the result belongs to, even when the user
    has selected a different game for inline queries."""
    from internationalization import _user_chat_from_update
    user = _user(1)
    gm.new_game(CHAT)
    gm.join_game(user, CHAT)
    other_chat = Chat(21, 'supergroup', title='Other')
    gm.new_game(other_chat, thread_id=7)
    gm.join_game(user, other_chat, thread_id=7)
    gm.userid_current[user.id] = gm.player_for_user_in_chat(user, CHAT)
    player_b = gm.player_for_user_in_chat(user, other_chat, thread_id=7)

    _, chat, thread_id = _user_chat_from_update(
        _chosen(user, _result(player_b, 'draw')))
    assert chat is other_chat
    assert thread_id == 7

    # A result without a game, and a plain inline query, use the selection.
    assert _user_chat_from_update(_chosen(user, 'none:nogame:0'))[1] is CHAT
    assert _user_chat_from_update(_inline_query(user))[1] is CHAT


@pytest.mark.asyncio
async def test_inline_list_offers_no_draw_to_the_next_player_during_colour_choice():
    game = _started_game(_user(1), _user(2), _user(3))
    current = game.current_player
    current.cards = [c.Card(None, None, c.DRAW_FOUR), c.Card(c.BLUE, '2')]
    await _act(current, c.DRAW_FOUR)
    following = current.next
    context = _context()

    await bot.reply_to_query(_inline_query(following.user), context)

    base_ids = [result.id.split(':')[1] for result in context.bot.answered[0]]
    assert 'draw' not in base_ids
