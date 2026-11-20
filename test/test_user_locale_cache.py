"""Tests for the cache on ``internationalization.user_locale_code``."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pony.orm import db_session

import settings
from internationalization import user_locale_code
from user_setting import UserSetting


def _set_lang(user_id, lang):
    with db_session:
        us = UserSetting.get(id=user_id) or UserSetting(id=user_id)
        us.lang = lang


def test_serves_cached_locale_until_cleared():
    _set_lang(9001, 'de_DE')
    user_locale_code.cache_clear()
    assert user_locale_code(9001) == 'de_DE'

    _set_lang(9001, 'es_ES')
    assert user_locale_code(9001) == 'de_DE'

    user_locale_code.cache_clear()
    assert user_locale_code(9001) == 'es_ES'


def test_user_without_row_gets_en_us():
    user_locale_code.cache_clear()
    assert user_locale_code(9002) == 'en_US'


@pytest.mark.asyncio
async def test_locale_select_updates_cached_locale(monkeypatch):
    monkeypatch.setattr(settings, 'send_async', AsyncMock())
    _set_lang(9003, 'de_DE')
    user_locale_code.cache_clear()
    assert user_locale_code(9003) == 'de_DE'

    update = MagicMock()
    update.message.from_user.id = 9003
    update.effective_user.id = 9003
    update.effective_message.is_topic_message = False
    context = MagicMock()
    context.match = [None, 'es_ES']

    await settings.locale_select(update, context)

    assert user_locale_code(9003) == 'es_ES'
