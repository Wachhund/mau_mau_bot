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


"""Logs update counts, event loop lag, game count and memory at a fixed
interval, to tell growing load apart from slowdown over uptime."""

import asyncio
import logging
import os
from collections import Counter

from telegram import Update
from telegram.ext import TypeHandler

from shared_vars import gm

logger = logging.getLogger(__name__)

# The loop lag is how late a sleep of this many seconds wakes up.
LAG_PROBE_SECONDS = 1.0

update_counts = Counter()
_task = None


def update_kind(update):
    """The update's type, with messages sent through the bot (played cards)
    counted apart from other messages."""
    for kind in Update.ALL_TYPES:
        value = getattr(update, kind)
        if value is not None:
            if kind == 'message' and value.via_bot is not None:
                return 'message_via_bot'
            return str(kind)
    return 'unknown'


async def count_update(update, context):
    update_counts[update_kind(update)] += 1


def rss_mib():
    """Resident memory of this process in MiB, or None off Linux."""
    try:
        with open('/proc/self/statm') as statm:
            pages = int(statm.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * os.sysconf('SC_PAGE_SIZE') / 2**20


def report(lags, seconds):
    total = sum(update_counts.values())
    kinds = ', '.join(f'{kind} {n}' for kind, n in update_counts.most_common())
    mean_lag = sum(lags) / len(lags) if lags else 0.0
    max_lag = max(lags, default=0.0)
    rss = rss_mib()
    logger.info(
        "%d updates in %.0f s (%.1f/s)%s | loop lag mean %.0f ms, max %.0f ms"
        " | %d games, %d players | RSS %s",
        total, seconds, total / seconds if seconds else 0.0,
        f': {kinds}' if kinds else '', mean_lag * 1000, max_lag * 1000,
        len(gm.games_by_id), len(gm.userid_current),
        f'{rss:.0f} MiB' if rss is not None else 'n/a')
    update_counts.clear()


async def _run(interval):
    loop = asyncio.get_running_loop()
    lags = []
    period_start = loop.time()
    while True:
        start = loop.time()
        await asyncio.sleep(LAG_PROBE_SECONDS)
        now = loop.time()
        lags.append(max(0.0, now - start - LAG_PROBE_SECONDS))
        if now - period_start >= interval:
            report(lags, now - period_start)
            lags = []
            period_start = now


def register(application, interval):
    """Count every update. An interval of 0 disables the stats."""
    if interval > 0:
        application.add_handler(TypeHandler(Update, count_update), group=-1)


def start(interval):
    """Start the report task. Needs the running event loop."""
    global _task
    if interval > 0 and _task is None:
        _task = asyncio.create_task(_run(interval), name='load_stats')


def stop():
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
