#!/usr/bin/env python3
"""
Dashboard — View your trade history and current P&L.
Usage: python3 dashboard.py
"""
import sys
import os
import sqlite3

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config

DB_PATH = os.path.join(PROJECT_ROOT, config.DB_PATH)
CSV_PATH = os.path.join(PROJECT_ROOT, config.CSV_PATH)


def show_dashboard():
    if not os.path.exists(DB_PATH):
        print("[ERROR] No trade database found. Run the bot first.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("""
            SELECT ts, symbol, side, qty, price, fee, realized_pnl, mode, order_id
            FROM trades ORDER BY ts DESC LIMIT 50
        """)
        trades = c.fetchall()
    except Exception:
        c.execute("SELECT * FROM trades ORDER BY rowid DESC LIMIT 50")
        trades = c.fetchall()
        col_names = [d[0] for d in c.description]
        print(f"[INFO] Columns: {col_names}")
        conn.close()
        return

    print("=" * 65)
    print("  TRADING BOT DASHBOARD")
    print("=" * 65)

    if not trades:
        print("\n  No trades recorded yet.")
        conn.close()
        return

    total_trades = len(trades)
    buys = sum(1 for t in trades if t[2] == "BUY")
    sells = sum(1 for t in trades if t[2] == "SELL")
    total_fee = sum(t[5] for t in trades if t[5])
    total_pnl = sum(t[6] for t in trades if t[6])

    import time
    print(f"\n  Total trades: {total_trades} ({buys} buys, {sells} sells)")
    print(f"  Total fees paid: {total_fee:.4f} USDT")
    print(f"  Total realized PnL: {total_pnl:+.2f} USDT")

    print(f"\n  {'Time':<20} {'Side':<6} {'Symbol':<10} {'Qty':>12} {'Price':>10} {'Fee':>8} {'PnL':>10} {'Mode':<6}")
    print("-" * 90)
    for t in trades[:20]:
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t[0] / 1000))
        side = t[2] or "?"
        symbol = t[1] or "?"
        qty = float(t[3]) if t[3] else 0
        price = float(t[4]) if t[4] else 0
        fee = float(t[5]) if t[5] else 0
        pnl = float(t[6]) if t[6] else 0
        mode = t[7] or "?"
        print(f"  {ts_str:<20} {side:<6} {symbol:<10} {qty:>12.6f} {price:>10.2f} {fee:>8.4f} {pnl:>+10.2f} {mode:<6}")

    if total_trades > 20:
        print(f"  ... and {total_trades - 20} more trades")

    try:
        import csv
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "datetime", "symbol", "side", "qty", "price", "fee", "realized_pnl", "mode", "order_id"])
            for t in trades:
                ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t[0] / 1000))
                writer.writerow([t[0], ts_str, t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8]])
        print(f"\n  Exported {total_trades} trades to {CSV_PATH}")
    except Exception as e:
        print(f"\n  [WARN] CSV export failed: {e}")

    conn.close()
    print("\n" + "=" * 65)


if __name__ == "__main__":
    show_dashboard()
