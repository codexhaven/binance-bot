#!/usr/bin/env python3
import os
import sqlite3
import time
from typing import Optional

# Ensure the project root is on the import path for any relative imports
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in os.sys.path:
    os.sys.path.insert(0, PROJECT_ROOT)

# ctx: codexhaven

DB_PATH = os.path.join(PROJECT_ROOT, "trades.db")

def _connect() -> sqlite3.Connection:
    """
    Create a SQLite connection with foreign keys enabled and row factory for dict‑like access.
    Returns:
        sqlite3.Connection: Active connection to the trades database.
    """
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db() -> None:
    """
    Initialise the SQLite database and create the trades table if it does not exist.
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
    with _connect() as conn:
        conn.execute(create_sql)
        conn.commit()

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
    order_id: str
) -> None:
    """
    Persist a single trade record to the SQLite database.

    Args:
        ts: Timestamp in milliseconds.
        symbol: Trading pair (e.g., "BTCUSDT").
        side: "BUY" or "SELL".
        qty: Quantity executed.
        price: Execution price.
        fee: Fee amount charged.
        fee_asset: Asset in which the fee was taken (e.g., "USDT").
        realized_pnl: Realised profit/loss for the trade (0 for market orders without closing).
        mode: "paper" or "live".
        order_id: Binance order identifier.
    """
    insert_sql = """
    INSERT INTO trades (
        ts, symbol, side, qty, price, fee, fee_asset, realized_pnl, mode, order_id
    ) VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    );
    """
    with _connect() as conn:
        conn.execute(
            insert_sql,
            (ts, symbol, side.upper(), qty, price, fee, fee_asset, realized_pnl, mode.lower(), order_id)
        )
        conn.commit()

def export_csv(filepath: str) -> None:
    """
    Export all trade records to a CSV file with a header row.

    Args:
        filepath: Destination path for the CSV file. Directories are created if missing.
    """
    # Ensure target directory exists
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

    select_sql = "SELECT * FROM trades ORDER BY ts ASC;"
    with _connect() as conn, open(filepath, "w", newline="", encoding="utf-8") as csv_file:
        # Write header
        header = [description[0] for description in conn.execute(select_sql).description]
        csv_file.write(",".join(header) + "\n")

        # Write rows
        for row in conn.execute(select_sql):
            csv_file.write(",".join(str(row[col]) for col in header) + "\n")

def get_last_trade(symbol: Optional[str] = None) -> Optional[sqlite3.Row]:
    """
    Retrieve the most recent trade, optionally filtered by symbol.

    Args:
        symbol: If provided, limit the search to this trading pair.

    Returns:
        sqlite3.Row containing the trade data or None if no trades exist.
    """
    query = "SELECT * FROM trades ORDER BY ts DESC LIMIT 1;"
    params = ()
    if symbol:
        query = "SELECT * FROM trades WHERE symbol = ? ORDER BY ts DESC LIMIT 1;"
        params = (symbol.upper(),)

    with _connect() as conn:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return row

if __name__ == "__main__":
    # Simple CLI for quick manual testing
    import argparse
    parser = argparse.ArgumentParser(description="Trade logger utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialise the trades database")
    log_parser = subparsers.add_parser("log", help="Log a new trade")
    log_parser.add_argument("--ts", type=int, default=int(time.time() * 1000), help="Timestamp ms")
    log_parser.add_argument("--symbol", required=True, help="Trading pair")
    log_parser.add_argument("--side", required=True, choices=["BUY", "SELL"], help="Side")
    log_parser.add_argument("--qty", type=float, required=True, help="Quantity")
    log_parser.add_argument("--price", type=float, required=True, help="Price")
    log_parser.add_argument("--fee", type=float, default=0.0, help="Fee amount")
    log_parser.add_argument("--fee_asset", default="USDT", help="Fee asset")
    log_parser.add_argument("--pnl", type=float, default=0.0, help="Realised PnL")
    log_parser.add_argument("--mode", default="paper", choices=["paper", "live"], help="Mode")
    log_parser.add_argument("--order_id", required=True, help="Order ID")

    export_parser = subparsers.add_parser("export", help="Export trades to CSV")
    export_parser.add_argument("filepath", help="Destination CSV file path")

    args = parser.parse_args()

    if args.command == "init":
        init_db()
        print(f"Database initialised at {DB_PATH}")
    elif args.command == "log":
        init_db()  # Ensure DB exists
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
    elif args.command == "export":
        export_csv(args.filepath)
        print(f"Trades exported to {args.filepath}")