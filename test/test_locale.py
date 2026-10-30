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


"""The locale stack lives in a ContextVar, so concurrent tasks do not see
each other's locales."""

import asyncio

import pytest

from internationalization import _, __, _locale_stack, locale_stack


@pytest.fixture(autouse=True)
def empty_stack():
    _locale_stack.set([])
    yield
    _locale_stack.set([])


@pytest.mark.asyncio
async def test_concurrent_tasks_have_isolated_stacks():
    results = {}
    first_inside = asyncio.Event()

    async def task_a():
        with locale_stack(['de_DE']):
            first_inside.set()
            await asyncio.sleep(0)  # let task_b run in between
            results['a'] = _.code

    async def task_b():
        await first_inside.wait()
        with locale_stack(['ru_RU']):
            await asyncio.sleep(0)
            results['b'] = _.code

    await asyncio.gather(task_a(), task_b())

    assert results == {'a': 'de_DE', 'b': 'ru_RU'}


@pytest.mark.asyncio
async def test_subtask_push_does_not_leak_into_the_parent():
    with locale_stack(['en_US']):
        async def subtask():
            _.push('zh_CN')
            assert _.code == 'zh_CN'

        await asyncio.create_task(subtask())

        assert _.code == 'en_US'


def test_push_and_pop_are_symmetric():
    _.push('de_DE')
    _.push('fr_FR')
    assert _.code == 'fr_FR'
    assert _.pop() == 'fr_FR'
    assert _.code == 'de_DE'
    assert _.pop() == 'de_DE'
    assert _.code is None
    assert _.pop() is None


def test_empty_stack_falls_back_to_english():
    assert _.code is None
    assert _("Test string") == "Test string"
    assert _("one thing", "{n} things", 3) == "{n} things"
    assert __("Game ended!") == "Game ended!"
    assert __("Game ended!", multi=True) == "Game ended!"
