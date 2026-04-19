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


"""Tests for resolve_result — the pure helper that maps a decoded inline-result
ID + user back to the game/player or to a structured "dead-game" outcome that
the handler can present to the user (AC-8)."""

from types import SimpleNamespace

from result_id import DecodedResult, PSEUDO_GAME_ID
from result_id_resolver import (DEAD_NO_CURRENT_GAME, DEAD_NOT_A_PLAYER,
                                DEAD_UNKNOWN_GAME, ResolvedResult,
                                resolve_result)


class _FakeGameManager:
    def __init__(self, games_by_id=None, userid_current=None):
        self._by_id = games_by_id or {}
        self.userid_current = userid_current or {}

    def game_by_id(self, game_id):
        return self._by_id.get(game_id)


def _make_game(game_id):
    chat = SimpleNamespace(id=42, title='G')
    return SimpleNamespace(id=game_id, chat=chat, thread_id=None, players=[])


def _add_player(game, user_id):
    user = SimpleNamespace(id=user_id)
    player = SimpleNamespace(user=user, game=game)
    game.players.append(player)
    return player


class TestResolveSuccess:
    def test_pseudo_game_id_returns_user_current_game(self):
        game = _make_game('g1')
        player = _add_player(game, 7)
        gm = _FakeGameManager(userid_current={7: player})

        decoded = DecodedResult(game_id=PSEUDO_GAME_ID, base_id='hand', anti_cheat=0)
        result = resolve_result(gm, decoded, user_id=7)

        assert isinstance(result, ResolvedResult)
        assert result.game is game
        assert result.player is player
        assert result.dead_reason is None

    def test_real_game_id_returns_game_and_matching_player(self):
        game = _make_game('abc123')
        player = _add_player(game, 99)
        gm = _FakeGameManager(games_by_id={'abc123': game})

        decoded = DecodedResult(game_id='abc123', base_id='r_5', anti_cheat=2)
        result = resolve_result(gm, decoded, user_id=99)

        assert result.game is game
        assert result.player is player
        assert result.dead_reason is None


class TestResolveDeadGame:
    """AC-8: dead-game cases must produce a structured reason."""

    def test_pseudo_id_without_current_game_is_no_current_game(self):
        gm = _FakeGameManager()
        decoded = DecodedResult(game_id=PSEUDO_GAME_ID, base_id='mode_classic', anti_cheat=0)
        result = resolve_result(gm, decoded, user_id=7)

        assert result.game is None
        assert result.player is None
        assert result.dead_reason == DEAD_NO_CURRENT_GAME

    def test_real_id_with_unknown_game_is_unknown_game(self):
        gm = _FakeGameManager(games_by_id={})
        decoded = DecodedResult(game_id='deadbe', base_id='r_5', anti_cheat=0)
        result = resolve_result(gm, decoded, user_id=99)

        assert result.dead_reason == DEAD_UNKNOWN_GAME

    def test_real_id_user_not_in_game_is_not_a_player(self):
        game = _make_game('abc123')
        # someone else is in this game, but not user 99
        _add_player(game, 1)
        gm = _FakeGameManager(games_by_id={'abc123': game})

        decoded = DecodedResult(game_id='abc123', base_id='r_5', anti_cheat=0)
        result = resolve_result(gm, decoded, user_id=99)

        assert result.dead_reason == DEAD_NOT_A_PLAYER
