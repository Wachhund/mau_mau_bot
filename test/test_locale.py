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


import asyncio
from contextvars import ContextVar
import pytest


# Replicate the ContextVar mechanism from internationalization.py
# without importing shared_vars (which requires a valid bot token).
_locale_stack: ContextVar[list] = ContextVar('test_locale_stack', default=[])


class _TestUnderscore:
    """Minimal reproduction of _Underscore for testing ContextVar isolation"""

    def push(self, locale):
        stack = _locale_stack.get([])
        _locale_stack.set(stack + [locale])

    def pop(self):
        stack = _locale_stack.get([])
        if stack:
            locale = stack[-1]
            _locale_stack.set(stack[:-1])
            return locale
        return None

    @property
    def code(self):
        stack = _locale_stack.get([])
        if stack:
            return stack[-1]
        return None

    def __call__(self, singular, plural=None, n=1, locale=None):
        if not locale:
            stack = _locale_stack.get([])
            locale = stack[-1] if stack else 'en_US'
        if n == 1:
            return singular
        return plural


_ = _TestUnderscore()


def set_locale_stack(locales):
    _locale_stack.set(list(locales))


class TestContextVarIsolation:
    """Tests that locale stack is isolated per asyncio task via ContextVar"""

    @pytest.mark.asyncio
    async def test_concurrent_tasks_have_isolated_stacks(self):
        """Two tasks pushing different locales should not interfere"""
        results = {}
        barrier = asyncio.Event()

        async def task_a():
            _.push('de_DE')
            barrier.set()
            await asyncio.sleep(0)  # yield to let task_b run
            results['a'] = _.code

        async def task_b():
            await barrier.wait()
            _.push('ru_RU')
            await asyncio.sleep(0)
            results['b'] = _.code

        await asyncio.gather(
            asyncio.create_task(task_a()),
            asyncio.create_task(task_b()),
        )

        assert results['a'] == 'de_DE'
        assert results['b'] == 'ru_RU'

    @pytest.mark.asyncio
    async def test_main_task_not_affected_by_subtask(self):
        """A subtask's locale push should not leak into the parent"""
        _.push('en_US')

        async def subtask():
            _.push('zh_CN')
            assert _.code == 'zh_CN'

        await asyncio.create_task(subtask())

        # Parent should still see en_US, not zh_CN
        assert _.code == 'en_US'
        _.pop()

    @pytest.mark.asyncio
    async def test_set_locale_stack_for_jobs(self):
        """set_locale_stack should replace the current task's stack"""
        set_locale_stack(['de_DE', 'es_ES'])
        stack = _locale_stack.get([])
        assert stack == ['de_DE', 'es_ES']
        assert _.code == 'es_ES'

    @pytest.mark.asyncio
    async def test_empty_stack_returns_none(self):
        """Empty locale stack should return None for code"""
        _locale_stack.set([])
        assert _.code is None

    @pytest.mark.asyncio
    async def test_push_pop_symmetry(self):
        """Push and pop should be symmetric"""
        _locale_stack.set([])
        _.push('de_DE')
        _.push('fr_FR')
        assert _.code == 'fr_FR'
        result = _.pop()
        assert result == 'fr_FR'
        assert _.code == 'de_DE'
        _.pop()
        assert _.code is None

    @pytest.mark.asyncio
    async def test_underscore_falls_back_to_en_US(self):
        """Calling _() with empty stack should use en_US (return original string)"""
        _locale_stack.set([])
        result = _("Test string")
        assert result == "Test string"
