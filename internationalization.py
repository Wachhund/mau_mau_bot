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


import gettext
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from locales import available_locales
from pony.orm import db_session
from user_setting import UserSetting
from shared_vars import gm

GETTEXT_DOMAIN = 'unobot'
GETTEXT_DIR = 'locales'

_locale_stack: ContextVar[list] = ContextVar('locale_stack', default=[])


class _Underscore(object):
    """Class to emulate flufl.i18n behaviour, but with plural support"""
    def __init__(self):
        self.translators = {
            locale: gettext.GNUTranslations(
                open(gettext.find(
                    GETTEXT_DOMAIN, GETTEXT_DIR, languages=[locale]
                ), 'rb')
            )
            for locale
            in available_locales.keys()
            if locale != 'en_US'  # No translation file for en_US
        }

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

    @property
    def locale_stack(self):
        return _locale_stack.get([])

    def __call__(self, singular, plural=None, n=1, locale=None):
        if not locale:
            stack = _locale_stack.get([])
            if stack:
                locale = stack[-1]
            else:
                locale = 'en_US'

        if locale not in self.translators.keys():
            if n == 1:
                return singular
            else:
                return plural

        translator = self.translators[locale]

        if plural is None:
            return translator.gettext(singular)
        else:
            return translator.ngettext(singular, plural, n)

_ = _Underscore()


def __(singular, plural=None, n=1, multi=False):
    """Translates text into all locales on the stack"""
    translations = list()
    stack = _locale_stack.get([])

    if not multi and len(set(stack)) >= 1:
        translations.append(_(singular, plural, n, 'en_US'))

    else:
        for locale in stack:
            translation = _(singular, plural, n, locale)

            if translation not in translations:
                translations.append(translation)

    return '\n'.join(translations)


@contextmanager
def locale_stack(locales):
    """Replace the current task's locale stack for the duration of the block,
    restoring the previous stack on exit (even when the block raises).

    Used by both :func:`game_locales` (decorator wrapping a request handler)
    and :func:`actions.skip_job` (job-queue callback that re-enters with the
    update's locale snapshot)."""
    saved = _locale_stack.get([])
    _locale_stack.set(list(locales))
    try:
        yield
    finally:
        _locale_stack.set(saved)


def set_locale_stack(locales):
    """Set the locale stack directly. Kept as a thin shim around the context
    manager for callers that don't have a natural ``with``-scope."""
    _locale_stack.set(list(locales))


def user_locale(func):
    @wraps(func)
    async def wrapped(update, context, *pargs, **kwargs):
        user = _user_chat_from_update(update)[0]
        # chat and thread_id are unused here

        with db_session:
            us = UserSetting.get(id=user.id)

        locale = us.lang if (us and us.lang != 'en') else 'en_US'
        new_stack = _locale_stack.get([]) + [locale]
        with locale_stack(new_stack):
            return await func(update, context, *pargs, **kwargs)
    return wrapped


def game_locales(func):
    @wraps(func)
    async def wrapped(update, context, *pargs, **kwargs):
        user, chat, thread_id = _user_chat_from_update(update)
        player = gm.player_for_user_in_chat(user, chat, thread_id=thread_id) \
            if chat is not None else None

        new_stack = list(_locale_stack.get([]))
        if player:
            for game_player in player.game.players:
                with db_session:
                    us = UserSetting.get(id=game_player.user.id)
                loc = us.lang if (us and us.lang != 'en') else 'en_US'
                if loc not in new_stack:
                    new_stack.append(loc)

        with locale_stack(new_stack):
            return await func(update, context, *pargs, **kwargs)
    return wrapped


def _user_chat_from_update(update):
    user = update.effective_user
    chat = update.effective_chat
    msg = update.effective_message
    thread_id = msg.message_thread_id if msg is not None else None

    if chat is None and user is not None and user.id in gm.userid_current:
        # Inline-query path: borrow the chat from the user's currently active
        # game so that the locale decorators have something to work with.
        current_game = gm.userid_current[user.id].game
        chat = current_game.chat
        thread_id = current_game.thread_id

    return user, chat, thread_id
