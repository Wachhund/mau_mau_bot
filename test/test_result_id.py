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


from result_id import (PSEUDO_GAME_ID, encode_result_id, decode_result_id,
                       encode_results_list, DecodedResult)


class TestEncode:
    """AC-6: result_id format is <game_id>:<base_id>:<anti_cheat>."""

    def test_encode_card_result(self):
        rid = encode_result_id(game_id='abc123', base_id='r_5', anti_cheat=3)
        assert rid == 'abc123:r_5:3'

    def test_encode_action_result(self):
        rid = encode_result_id(game_id='abc123', base_id='draw', anti_cheat=0)
        assert rid == 'abc123:draw:0'

    def test_encode_pseudo_game_result(self):
        rid = encode_result_id(game_id=PSEUDO_GAME_ID, base_id='hand', anti_cheat=0)
        assert rid == 'none:hand:0'


class TestDecode:
    """AC-7, AC-9: decoder splits cleanly and preserves anti-cheat."""

    def test_decode_card_result(self):
        d = decode_result_id('abc123:r_5:3')
        assert d == DecodedResult(game_id='abc123', base_id='r_5', anti_cheat=3)

    def test_decode_color_choice(self):
        d = decode_result_id('abc123:red:0')
        assert d.base_id == 'red'
        assert d.anti_cheat == 0

    def test_decode_pseudo_game(self):
        d = decode_result_id('none:hand:0')
        assert d.game_id == PSEUDO_GAME_ID
        assert d.base_id == 'hand'

    def test_decode_handles_base_id_with_no_extra_colons(self):
        d = decode_result_id('abc123:mode_classic:0')
        assert d.base_id == 'mode_classic'

    def test_decode_returns_none_for_old_two_field_format(self):
        # AC-8: old result IDs (after a bot restart while a game was running)
        # must not crash — the decoder simply returns None.
        assert decode_result_id('draw:0') is None

    def test_decode_returns_none_for_garbage(self):
        assert decode_result_id('garbage') is None
        assert decode_result_id('') is None


class _FakeFrozenResult:
    """Mimics telegram.InlineQueryResult: id is only writable within _unfrozen()."""

    def __init__(self, id):
        object.__setattr__(self, '_frozen', False)
        object.__setattr__(self, 'id', id)
        object.__setattr__(self, '_frozen', True)

    def __setattr__(self, name, value):
        if name == 'id' and self._frozen:
            raise AttributeError(f"Attribute `{name}` can't be set!")
        object.__setattr__(self, name, value)

    class _Unfrozen:
        def __init__(self, parent):
            self.parent = parent

        def __enter__(self):
            object.__setattr__(self.parent, '_frozen', False)
            return self.parent

        def __exit__(self, *exc):
            object.__setattr__(self.parent, '_frozen', True)

    def _unfrozen(self):
        return _FakeFrozenResult._Unfrozen(self)


class TestEncodeResultsList:
    """AC-6: every result in the list gets the <game_id>:<base_id>:<anti_cheat>
    encoding — including non-game sentinels."""

    def test_encodes_every_result_in_list(self):
        results = [_FakeFrozenResult('r_5'), _FakeFrozenResult('draw')]

        encode_results_list(results, game_id='abc123', anti_cheat=3)

        assert results[0].id == 'abc123:r_5:3'
        assert results[1].id == 'abc123:draw:3'

    def test_encodes_with_pseudo_game_id(self):
        results = [_FakeFrozenResult('nogame')]

        encode_results_list(results, game_id=PSEUDO_GAME_ID, anti_cheat=0)

        assert results[0].id == 'none:nogame:0'

    def test_encodes_empty_list_is_noop(self):
        results = []
        encode_results_list(results, game_id='abc123', anti_cheat=0)
        assert results == []
