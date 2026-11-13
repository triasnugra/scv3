import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scalp.config import load_config  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


def bars(rows, start="2026-01-01 00:00", freq="15min"):
    """rows: [(o,h,l,c), ...] -> DataFrame candle."""
    idx = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 100.0
    return df
