"""CSV loaders with schema validation for each FX-FRO data type.

Also provides load_surveillance_yaml() which loads the constant base workflow
YAML. The base YAML is read-only — agents consume it, never write to it.
"""

import logging
from pathlib import Path

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base workflow YAML — loaded once, never modified
# ---------------------------------------------------------------------------

def load_surveillance_yaml(path: str = "fx_fro_surveillance.yaml") -> dict:
    """Load the constant base surveillance workflow YAML (read-only).

    This file defines the fixed scan parameters — thresholds, lookbacks,
    step definitions. It is the immutable baseline. Each agentic cycle
    produces its own attempt_N.yaml that documents what it changed from
    this base, but the base itself is never touched.
    """
    p = Path(path)
    if not p.exists():
        logger.error(f"Base workflow YAML not found at: {path}")
        return {}
    with open(p) as f:
        return yaml.safe_load(f)


# Loaded once at import time — treat as a read-only constant
BASE_WORKFLOW: dict = load_surveillance_yaml()

ORDERS_SCHEMA = {
    "order_id": str,
    "entity_id": str,
    "symbol": str,
    "side": str,
    "order_type": str,
    "quantity": float,
    "price": float,
    "timestamp": str,
    "status": str,
    "counterparty": str,
    "session": str,
}

TRADES_SCHEMA = {
    "trade_id": str,
    "entity_id": str,
    "symbol": str,
    "side": str,
    "quantity": float,
    "price": float,
    "timestamp": str,
    "counterparty": str,
    "trade_type": str,
    "session": str,
}

MARKET_DATA_SCHEMA = {
    "symbol": str,
    "timestamp": str,
    "bid": float,
    "ask": float,
    "mid": float,
    "volume": float,
    "spread_bps": float,
}

COMMS_SCHEMA = {
    "comm_id": str,
    "entity_id": str,
    "timestamp": str,
    "channel": str,
    "content": str,
    "participants": str,
}


def _load_csv(path: str, schema: dict, datetime_col: str = "timestamp") -> pd.DataFrame:
    """Load and validate a CSV file against a schema."""
    p = Path(path)
    if not p.exists():
        logger.warning(f"Data file not found: {path}. Returning empty DataFrame.")
        return pd.DataFrame(columns=list(schema.keys()))
    df = pd.read_csv(p, dtype=str)
    # Add missing columns
    for col in schema:
        if col not in df.columns:
            logger.warning(f"Column '{col}' missing from {path}; filling with empty string.")
            df[col] = ""
    # Cast numeric columns
    for col, dtype in schema.items():
        if dtype == float:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    # Parse timestamp
    if datetime_col in df.columns:
        df[datetime_col] = pd.to_datetime(df[datetime_col], errors="coerce")
    return df[list(schema.keys())]


def load_orders(path: str = "data/orders.csv") -> pd.DataFrame:
    return _load_csv(path, ORDERS_SCHEMA)


def load_trades(path: str = "data/trades.csv") -> pd.DataFrame:
    return _load_csv(path, TRADES_SCHEMA)


def load_market_data(path: str = "data/market_data.csv") -> pd.DataFrame:
    return _load_csv(path, MARKET_DATA_SCHEMA)


def load_comms(path: str = "data/comms.csv") -> pd.DataFrame:
    return _load_csv(path, COMMS_SCHEMA)
