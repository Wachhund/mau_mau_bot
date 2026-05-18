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


"""Tests for ``internationalization.locale_stack`` (the real context manager,
not the in-test replica used by ``test_locale.py``).

``internationalization`` indirectly imports ``shared_vars`` which needs a
valid bot token, so stub ``config`` before importing."""

import os
import sys
import types

# Stub config + DB env before any import of internationalization / shared_vars
if 'config' not in sys.modules:
    fake_config = types.ModuleType('config')
    for k, v in [('TOKEN', '0:abc'), ('WORKERS', 0), ('ADMIN_LIST', []),
                 ('OPEN_LOBBY', True), ('DEFAULT_GAMEMODE', 'classic'),
                 ('ENABLE_TRANSLATIONS', False), ('WAITING_TIME', 90),
                 ('MIN_PLAYERS', 2), ('TIME_REMOVAL_AFTER_SKIP', 20),
                 ('MIN_FAST_TURN_TIME', 8), ('BOT_USERNAME', 'm')]:
        setattr(fake_config, k, v)
    sys.modules['config'] = fake_config
os.environ.setdefault('UNO_DB', ':memory:')

from internationalization import _locale_stack, locale_stack, set_locale_stack


class TestLocaleStackContextManager:
    """jh0ker internationalization.py:168 — `locale_stack` is a reusable
    context manager that restores the previous stack on exit."""

    def test_replaces_and_restores(self):
        _locale_stack.set(['de_DE'])
        with locale_stack(['fr_FR', 'es_ES']):
            assert _locale_stack.get([]) == ['fr_FR', 'es_ES']
        assert _locale_stack.get([]) == ['de_DE']

    def test_restores_on_exception(self):
        _locale_stack.set(['en_US'])
        try:
            with locale_stack(['xx_XX']):
                raise RuntimeError('boom')
        except RuntimeError:
            pass
        assert _locale_stack.get([]) == ['en_US']

    def test_empty_input_clears_within_block_then_restores(self):
        _locale_stack.set(['de_DE'])
        with locale_stack([]):
            assert _locale_stack.get([]) == []
        assert _locale_stack.get([]) == ['de_DE']

    def test_nested_blocks_restore_correctly(self):
        _locale_stack.set(['a'])
        with locale_stack(['b']):
            with locale_stack(['c']):
                assert _locale_stack.get([]) == ['c']
            assert _locale_stack.get([]) == ['b']
        assert _locale_stack.get([]) == ['a']

    def test_set_locale_stack_shim_still_works(self):
        """set_locale_stack is kept as a non-CM shim for callers without a
        natural with-scope. It must still set the stack directly."""
        set_locale_stack(['xx_XX', 'yy_YY'])
        assert _locale_stack.get([]) == ['xx_XX', 'yy_YY']
        _locale_stack.set([])  # cleanup
