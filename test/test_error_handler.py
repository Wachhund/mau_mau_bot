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


"""Tests for utils.error — addresses Copilot's utils.py:84 finding on PR #138:
``logger.exception(context.error)`` outside an active exception context logs
``NoneType: None`` instead of the real traceback."""

import logging
import os
import sys
import types

import pytest

# Stub config + DB env before importing utils (which pulls shared_vars)
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

from utils import error


class _FakeContext:
    def __init__(self, exc):
        self.error = exc


@pytest.mark.asyncio
async def test_error_logs_real_traceback_when_context_has_error(caplog):
    """When PTB hands us the original exception, the log record must carry
    its traceback (not 'NoneType: None')."""
    exc = ValueError("boom: real exception")

    with caplog.at_level(logging.ERROR, logger='utils'):
        await error(update=None, context=_FakeContext(exc))

    assert len(caplog.records) == 1
    rec = caplog.records[0]
    # exc_info must carry the exception object so the formatter can render the
    # real traceback. Plain logger.exception() outside `except` produces None.
    assert rec.exc_info is not None, \
        "error() must attach exc_info so the traceback is logged"
    assert rec.exc_info[1] is exc, \
        "exc_info[1] should be the original exception instance"


@pytest.mark.asyncio
async def test_error_handles_context_without_error_field(caplog):
    """Some PTB error scenarios pass a context whose .error is None. The
    handler must not crash and must still log something useful."""
    with caplog.at_level(logging.ERROR, logger='utils'):
        await error(update=None, context=_FakeContext(None))

    assert len(caplog.records) == 1
    # No exc_info expected when there is no exception to attach
    assert caplog.records[0].exc_info is None
