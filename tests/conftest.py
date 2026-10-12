"""Test collection settings.

The self-hosted compiler under `selfhost/` is frozen (tag `selfhost-freeze`): the language is
developed in Python first. Its parity tests run only with GG_SELFHOST=1.
"""
import os

SELFHOST_TESTS = ["test_selfhost_lexer.py", "test_selfhost_parser.py", "test_selfhost_typecheck.py"]

collect_ignore = [] if os.environ.get("GG_SELFHOST") else SELFHOST_TESTS
