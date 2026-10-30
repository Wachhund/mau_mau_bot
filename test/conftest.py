"""Test environment defaults.

Importing most project modules pulls in ``config`` (which exits without a bot
token) and ``shared_vars`` (which builds the Application and binds the
database), so set the environment before any of them are imported.
"""

import os

import pytest

os.environ.setdefault("TOKEN", "1:test")
os.environ.setdefault("UNO_DB", ":memory:")


@pytest.fixture(autouse=True)
def no_promotions(monkeypatch):
    """Ending a game may advertise other bots; tests have no chat to send to."""
    import actions

    async def no_promotion(*args, **kwargs):
        return None

    monkeypatch.setattr(actions, "send_promotion", no_promotion)
