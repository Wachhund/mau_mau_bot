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


def user_locale(func):
    @wraps(func)
    async def wrapped(update, context, *pargs, **kwargs):
        user = _user_chat_from_update(update)[0]

        with db_session:
            us = UserSetting.get(id=user.id)

        if us and us.lang != 'en':
            _.push(us.lang)
        else:
            _.push('en_US')

        try:
            result = await func(update, context, *pargs, **kwargs)
            return result
        finally:
            _.pop()
    return wrapped


def game_locales(func):
    @wraps(func)
    async def wrapped(update, context, *pargs, **kwargs):
        user, chat = _user_chat_from_update(update)
        player = gm.player_for_user_in_chat(user, chat)
        locales = list()

        if player:
            for player in player.game.players:
                with db_session:
                    us = UserSetting.get(id=player.user.id)

                if us and us.lang != 'en':
                    loc = us.lang
                else:
                    loc = 'en_US'

                if loc in locales:
                    continue

                _.push(loc)
                locales.append(loc)

        try:
            result = await func(update, context, *pargs, **kwargs)
            return result
        finally:
            while _.code:
                _.pop()
    return wrapped


def set_locale_stack(locales):
    """Set the locale stack directly, for use in job callbacks"""
    _locale_stack.set(list(locales))


def _user_chat_from_update(update):
    user = update.effective_user
    chat = update.effective_chat

    if chat is None and user is not None and user.id in gm.userid_current:
        chat = gm.userid_current.get(user.id).game.chat

    return user, chat
