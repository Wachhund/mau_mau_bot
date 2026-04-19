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


"""Map a decoded inline-result ID + user to a game/player, or to a structured
"dead-game" reason the handler can surface to the user (AC-8)."""

from dataclasses import dataclass
from typing import Optional

from result_id import DecodedResult, PSEUDO_GAME_ID


DEAD_NO_CURRENT_GAME = 'no_current_game'
DEAD_UNKNOWN_GAME = 'unknown_game'
DEAD_NOT_A_PLAYER = 'not_a_player'


@dataclass
class ResolvedResult:
    game: Optional[object]
    player: Optional[object]
    dead_reason: Optional[str]


def resolve_result(gm, decoded: DecodedResult, user_id: int) -> ResolvedResult:
    """Return the (game, player) pair for this decoded result, or a dead reason.

    The handler presents ``dead_reason`` to the user so that no inline selection
    disappears silently when the game has ended mid-interaction.
    """
    if decoded.game_id == PSEUDO_GAME_ID:
        player = gm.userid_current.get(user_id)
        if player is None:
            return ResolvedResult(game=None, player=None,
                                  dead_reason=DEAD_NO_CURRENT_GAME)
        return ResolvedResult(game=player.game, player=player, dead_reason=None)

    game = gm.game_by_id(decoded.game_id)
    if game is None:
        return ResolvedResult(game=None, player=None,
                              dead_reason=DEAD_UNKNOWN_GAME)

    for player in game.players:
        if player.user.id == user_id:
            return ResolvedResult(game=game, player=player, dead_reason=None)

    return ResolvedResult(game=game, player=None, dead_reason=DEAD_NOT_A_PLAYER)
