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


from config import TOKEN
import os
from telegram.ext import AIORateLimiter, Application

from database import db
from game_manager import GameManager
from uno_update_processor import UnoUpdateProcessor

db.bind('sqlite', os.getenv('UNO_DB', 'uno.sqlite3'), create_db=True)
db.generate_mapping(create_tables=True)

gm = GameManager()


def _resolve_game_id(game_id):
    """Map a Game.id back to (chat_id, thread_id) for UpdateProcessor routing."""
    game = gm.game_by_id(game_id)
    if game is None:
        return None
    return (game.chat.id, game.thread_id)


# An update waiting for its chat's lock occupies one of these slots, so the
# count is well above the number of chats expected to be busy at once;
# otherwise a backlog in a few chats could stall inline queries, which only
# need a slot.
update_processor = UnoUpdateProcessor(
    max_concurrent_updates=2048,
    game_resolver=_resolve_game_id,
)

_TIMEOUT = 2.5  # aggressive default, matches pre-v22 behaviour

# The rate limiter queues requests to stay within Telegram's bot-wide limit
# (30 per second), which matters when /new notifies many subscribers at
# once. The per-group limit (20 per minute) is left off: game messages are
# sent while the game's lock is held, so queueing them would pace the game
# itself. A group that exceeds the limit gets a 429 and loses that message,
# as before the migration.
application = (Application.builder()
               .token(TOKEN)
               .concurrent_updates(update_processor)
               .rate_limiter(AIORateLimiter(group_max_rate=0))
               .read_timeout(_TIMEOUT)
               .write_timeout(_TIMEOUT)
               .connect_timeout(_TIMEOUT)
               .build())
