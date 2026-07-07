#!/bin/bash
# Run AI bot on both ETH and BTC simultaneously in background
cd ~/binance-bot

echo "Starting AI bots for ETH and BTC on 15m..."
echo "Threshold: 70% (expect ~2-4 trades per day)"
echo ""

# Run ETH in background, log to file
python3 cli.py ETHUSDT 15m paper > eth_ai_log.txt 2>&1 &
ETH_PID=$!
echo "ETH bot started (PID: $ETH_PID) → logging to eth_ai_log.txt"

# Run BTC in background, log to file  
python3 cli.py BTCUSDT 15m paper > btc_ai_log.txt 2>&1 &
BTC_PID=$!
echo "BTC bot started (PID: $BTC_PID) → logging to btc_ai_log.txt"

echo ""
echo "Both bots running. To watch live logs:"
echo "  tail -f eth_ai_log.txt"
echo "  tail -f btc_ai_log.txt"
echo ""
echo "To stop both: kill $ETH_PID $BTC_PID"
echo ""

# Wait and show combined live output
echo "=== LIVE OUTPUT (both bots) ==="
tail -f eth_ai_log.txt btc_ai_log.txt &
TAIL_PID=$!

# Wait for Ctrl+C
trap "kill $ETH_PID $BTC_PID $TAIL_PID 2>/dev/null; echo 'Bots stopped.'; exit" INT TERM
wait
