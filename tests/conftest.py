"""Root conftest: sys.path setup and shared fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ── sys.path setup ──────────────────────────────────────────────────────────
# Mirror Docker import resolution so tests can import from all three packages.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "mcp-server" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "chat-server" / "src"))

# ── MCP import compatibility ────────────────────────────────────────────────
# The project (Docker) uses mcp 1.20.0 which exports `streamable_http_client`,
# but locally-installed versions may export `streamablehttp_client` instead.
# Patch the module so imports succeed regardless of version.
try:
    from mcp.client.streamable_http import streamable_http_client  # noqa: F401
except ImportError:
    import mcp.client.streamable_http as _sh
    if hasattr(_sh, "streamablehttp_client"):
        _sh.streamable_http_client = _sh.streamablehttp_client

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def pytest_collection_modifyitems(items):
    """Auto-apply 'unit' marker to tests in tests/unit/ and 'e2e' to tests in tests/e2e/."""
    for item in items:
        test_path = str(item.fspath)
        if "/unit/" in test_path and "unit" not in [m.name for m in item.iter_markers()]:
            item.add_marker(pytest.mark.unit)
        elif "/e2e/" in test_path and "e2e" not in [m.name for m in item.iter_markers()]:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture()
def sample_csv_path() -> Path:
    return FIXTURES_DIR / "sample_data.csv"


@pytest.fixture()
def special_columns_csv_path() -> Path:
    return FIXTURES_DIR / "special_columns.csv"


@pytest.fixture()
def empty_headers_csv_path() -> Path:
    return FIXTURES_DIR / "empty_headers.csv"


@pytest.fixture()
def unicode_csv_path() -> Path:
    return FIXTURES_DIR / "unicode_data.csv"


@pytest.fixture()
def test_db(tmp_path):
    """Yield a temporary file-based SQLite DB path, cleaned up automatically by pytest."""
    db_path = str(tmp_path / "test.db")
    yield db_path
