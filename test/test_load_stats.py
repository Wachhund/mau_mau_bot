"""Tests for the periodic load stats in ``load_stats``."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from telegram import Update

import load_stats


def fake_update(kind, **fields):
    attrs = {str(t): None for t in Update.ALL_TYPES}
    attrs[kind] = SimpleNamespace(**fields)
    return SimpleNamespace(**attrs)


def test_update_kind_names_the_set_field():
    assert load_stats.update_kind(fake_update('inline_query')) == 'inline_query'
    assert load_stats.update_kind(
        fake_update('chosen_inline_result')) == 'chosen_inline_result'


def test_update_kind_splits_messages_sent_through_the_bot():
    assert load_stats.update_kind(
        fake_update('message', via_bot=None)) == 'message'
    assert load_stats.update_kind(
        fake_update('message', via_bot=object())) == 'message_via_bot'


def test_report_logs_counts_and_resets(caplog):
    load_stats.update_counts.clear()
    load_stats.update_counts.update({'inline_query': 3, 'message': 1})

    with caplog.at_level(logging.INFO, logger='load_stats'):
        load_stats.report([0.0, 0.25], 2.0)

    line = caplog.records[-1].getMessage()
    assert line.startswith('4 updates in 2 s (2.0/s): inline_query 3, message 1')
    assert 'loop lag mean 125 ms, max 250 ms' in line
    assert not load_stats.update_counts


@pytest.mark.asyncio
async def test_run_reports_once_per_interval(monkeypatch):
    reports = []
    monkeypatch.setattr(load_stats, 'LAG_PROBE_SECONDS', 0.01)
    monkeypatch.setattr(load_stats, 'report',
                        lambda lags, seconds: reports.append((len(lags), seconds)))

    load_stats.start(0.05)
    try:
        await asyncio.sleep(0.2)
    finally:
        load_stats.stop()

    assert reports
    assert all(n >= 1 and seconds >= 0.05 for n, seconds in reports)


def test_zero_interval_disables():
    load_stats.stop()
    load_stats.start(0)
    assert load_stats._task is None
