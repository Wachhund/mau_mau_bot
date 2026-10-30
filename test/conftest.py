"""Test environment defaults.

Importing most project modules pulls in ``config`` (which exits without a bot
token) and ``shared_vars`` (which builds the Application and binds the
database), so set the environment before any of them are imported.
"""

import os

os.environ.setdefault("TOKEN", "1:test")
os.environ.setdefault("UNO_DB", ":memory:")
