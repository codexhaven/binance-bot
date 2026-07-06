#!/usr/bin/env python3
"""
Trade logger module.

Provides SQLite‑backed persistence for trade records, a simple CLI for manual
operations and helper functions for other components of the bot.

Functions
---------
_connect() -> sqlite3.Connection
    Create a SQLite connection with foreign‑key support and a Row factory.

init_db() -> None
    Initialise the database and create the ``trades`` table if it does not exist.

log_trade(ts, symbol, side, qty, price, fee, fee_asset,
          realized_pnl, mode, order_id) -> None
    Insert a single trade record after basic validation.

export_csv(filepath) -> None
    Export all stored trades to a CSV file, creating missing directories.

get_last_trade(symbol=None) -> Optional[sqlite3.Row]
    Return the most recent trade, optionally filtered by ``symbol``.
"""

import os
import sys
import sqlite3
import time
from typing import Optional

# Ensure the project root is on the import path for any relative imports
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trades.db")


def _connect() -> sqlite3.Connection:
    """
    Create a SQLite connection with foreign keys enabled and a row factory
    for dict‑like access.

    Returns
    -------
    sqlite3.Connection
        Active connection to the trades database.

    Raises
    ------
    sqlite3.Error
        If the connection cannot be established.
    """
    try:
        conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to connect to SQLite database at {DB_PATH}") from exc


def init_db() -> None:
    """
    Initialise the SQLite database and create the ``trades`` table if it does
    not exist.

    The table schema:
        id            INTEGER PRIMARY KEY AUTOINCREMENT
        ts            INTEGER   – Unix epoch ms of the trade
        symbol        TEXT
        side          TEXT      – BUY or SELL
        qty           REAL
        price         REAL
        fee           REAL
        fee_asset     TEXT
        realized_pnl  REAL
        mode          TEXT      – 'paper' or 'live'
        order_id      TEXT
    """
    create_sql = """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        qty REAL NOT NULL,
        price REAL NOT NULL,
        fee REAL NOT NULL,
        fee_asset TEXT NOT NULL,
        realized_pnl REAL NOT NULL,
        mode TEXT NOT NULL,
        order_id TEXT NOT NULL
    );
    """
    try:
        with _connect() as conn:
            conn.execute(create_sql)
            conn.commit()
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to initialise the trades database") from exc


def _validate_trade_inputs(
    ts: int,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    fee: float,
    fee_asset: str,
    realized_pnl: float,
    mode: str,
    order_id: str,
) -> None:
    """
    Perform basic validation of trade parameters.

    Raises
    ------
    ValueError
        If any parameter is out of expected bounds or malformed.
    """
    if not isinstance(ts, int) or ts <= 0:
        raise ValueError("Timestamp must be a positive integer (ms).")
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non‑empty string.")
    if side.upper() not in {"BUY", "SELL"}:
        raise ValueError("Side must be either 'BUY' or 'SELL'.")
    if qty <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if price <= 0:
        raise ValueError("Price must be greater than zero.")
    if fee < 0:
        raise ValueError("Fee cannot be negative.")
    if not fee_asset or not isinstance(fee_asset, str):
        raise ValueError("Fee asset must be a non‑empty string.")
    if not isinstance(realized_pnl, (int, float)):
        raise ValueError("Realised PnL must be numeric.")
    if mode.lower() not in {"paper", "live"}:
        raise ValueError("Mode must be either 'paper' or 'live'.")
    if not order_id or not isinstance(order_id, str):
        raise ValueError("Order ID must be a non‑empty string.")


def log_trade(
    ts: int,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    fee: float,
    fee_asset: str,
    realized_pnl: float,
    mode: str,
    order_id: str,
) -> None:
    """
    Persist a single trade record to the SQLite database.

    Parameters
    ----------
    ts : int
        Timestamp in milliseconds.
    symbol : str
        Trading pair (e.g., "BTCUSDT").
    side : str
        "BUY" or "SELL".
    qty : float
        Quantity executed.
    price : float
        Execution price.
    fee : float
        Fee amount charged.
    fee_asset : str
        Asset in which the fee was taken (e.g., "USDT").
    realized_pnl : float
        Realised profit/loss for the trade (0 for market orders without closing).
    mode : str
        "paper" or "live".
    order_id : str
        Binance order identifier.

    Raises
    ------
    RuntimeError
        If the database operation fails.
    ValueError
        If any input validation fails.
    """
    _validate_trade_inputs(
        ts,
        symbol,
        side,
        qty,
        price,
        fee,
        fee_asset,
        realized_pnl,
        mode,
        order_id,
    )

    insert_sql = """
    INSERT INTO trades (
        ts, symbol, side, qty, price, fee, fee_asset, realized_pnl, mode, order_id
    ) VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    );
    """
    try:
        with _connect() as conn:
            conn.execute(
                insert_sql,
                (
                    ts,
                    symbol.upper(),
                    side.upper(),
                    qty,
                    price,
                    fee,
                    fee_asset.upper(),
                    realized_pnl,
                    mode.lower(),
                    order_id,
                ),
            )
            conn.commit()
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to log trade to the database") from exc


def export_csv(filepath: str) -> None:
    """
    Export all trade records to a CSV file with a header row.

    Parameters
    ----------
    filepath : str
        Destination path for the CSV file. Directories are created if missing.

    Raises
    ------
    RuntimeError
        If reading from the database or writing the file fails.
    """
    # Ensure target directory exists
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    select_sql = "SELECT * FROM trades ORDER BY ts ASC;"
    try:
        with _connect() as conn, open(filepath, "w", newline="", encoding="utf-8") as csv_file:
            cursor = conn.execute(select_sql)
            # Write header
            header = [description[0] for description in cursor.description]
            csv_file.write(",".join(header) + "\n")

            # Write rows
            for row in cursor:
                csv_file.write(",".join(str(row[col]) for col in header) + "\n")
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError(f"Failed to export trades to CSV at {filepath}") from exc


def get_last_trade(symbol: Optional[str] = None) -> Optional[sqlite3.Row]:
    """
    Retrieve the most recent trade, optionally filtered by symbol.

    Parameters
    ----------
    symbol : Optional[str]
        If provided, limit the search to this trading pair.

    Returns
    -------
    Optional[sqlite3.Row]
        Row containing the trade data or ``None`` if no trades exist.

    Raises
    ------
    RuntimeError
        If the database query fails.
    """
    if symbol:
        query = """
        SELECT * FROM trades
        WHERE symbol = ?
        ORDER BY ts DESC
        LIMIT 1;
        """
        params = (symbol.upper(),)
    else:
        query = "SELECT * FROM trades ORDER BY ts DESC LIMIT 1;"
        params = ()

    try:
        with _connect() as conn:
            cur = conn.execute(query, params)
            return cur.fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError("Failed to retrieve the last trade from the database") from exc


if __name__ == "__main__":
    # Simple CLI for quick manual testing
    import argparse

    parser = argparse.ArgumentParser(description="Trade logger utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialise the trades database")

    log_parser = subparsers.add_parser("log", help="Log a new trade")
    log_parser.add_argument(
        "--ts",
        type=int,
        default=int(time.time() * 1000),
        help="Timestamp in milliseconds",
    )
    log_parser.add_argument("--symbol", required=True, help="Trading pair")
    log_parser.add_argument(
        "--side", required=True, choices=["BUY", "SELL"], help="Side"
    )
    log_parser.add_argument("--qty", type=float, required=True, help="Quantity")
    log_parser.add_argument("--price", type=float, required=True, help="Price")
    log_parser.add_argument("--fee", type=float, default=0.0, help="Fee amount")
    log_parser.add_argument(
        "--fee_asset", default="USDT", help="Fee asset (e.g., USDT)"
    )
    log_parser.add_argument(
        "--pnl", type=float, default=0.0, help="Realised PnL"
    )
    log_parser.add_argument(
        "--mode",
        default="paper",
        choices=["paper", "live"],
        help="Mode (paper or live)",
    )
    log_parser.add_argument("--order_id", required=True, help="Order ID")

    export_parser = subparsers.add_parser(
        "export", help="Export trades to CSV"
    )
    export_parser.add_argument("filepath", help="Destination CSV file path")

    args = parser.parse_args()

    if args.command == "init":
        init_db()
        print(f"Database initialised at {DB_PATH}")
    elif args.command == "log":
        init_db()  # Ensure DB exists
        try:
            log_trade(
                ts=args.ts,
                symbol=args.symbol,
                side=args.side,
                qty=args.qty,
                price=args.price,
                fee=args.fee,
                fee_asset=args.fee_asset,
                realized_pnl=args.pnl,
                mode=args.mode,
                order_id=args.order_id,
            )
            print("Trade logged.")
        except Exception as e:
            print(f"Error logging trade: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "export":
        try:
            export_csv(args.filepath)
            print(f"Trades exported to {args.filepath}")
        except Exception as e:
            print(f"Error exporting CSV: {e}", file=sys.stderr)
            sys.exit(1)