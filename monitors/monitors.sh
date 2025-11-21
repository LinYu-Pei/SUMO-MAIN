#!/bin/bash

# 定義清理函數
cleanup() {
    echo "Cleaning up..."
    # Kill 所有子進程
    pkill -P $$
    exit 0
}

# 捕捉 SIGINT 信號 (Ctrl+C)
trap cleanup SIGINT

python3 GeofenceMonitor.py &
python3 RouteMonitor.py &
python3 MessageHandler.py &

wait