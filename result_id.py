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


"""Encoding/decoding for inline-result IDs.

Format: ``<game_id>:<base_id>:<anti_cheat>``
``game_id`` is :class:`game.Game.id` (uuid hex), or :data:`PSEUDO_GAME_ID`
("none") for results that do not belong to a specific game (mode picker, hand
preview, no-game placeholder).
"""

from dataclasses import dataclass
from typing import Optional


PSEUDO_GAME_ID = 'none'


@dataclass(frozen=True)
class DecodedResult:
    game_id: str
    base_id: str
    anti_cheat: int


def encode_result_id(*, game_id: str, base_id: str, anti_cheat: int) -> str:
    return f'{game_id}:{base_id}:{anti_cheat}'


def encode_results_list(results, *, game_id: str, anti_cheat: int) -> None:
    """Re-encode every ``id`` in an inline-result list in-place.

    Telegram inline-result objects are frozen in python-telegram-bot v22, so we
    use their ``_unfrozen()`` context manager to mutate ``id``.
    """
    prefix = f'{game_id}:'
    suffix = f':{anti_cheat}'
    for result in results:
        with result._unfrozen():
            result.id = prefix + result.id + suffix


def decode_result_id(result_id: str) -> Optional[DecodedResult]:
    if not result_id:
        return None
    parts = result_id.split(':', 2)
    if len(parts) != 3:
        return None
    game_id, base_id, anti_cheat_str = parts
    if not game_id or not base_id:
        return None
    try:
        anti_cheat = int(anti_cheat_str)
    except ValueError:
        return None
    return DecodedResult(game_id=game_id, base_id=base_id, anti_cheat=anti_cheat)
