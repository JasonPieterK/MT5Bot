"""Tracks order-send latency and requote frequency per symbol, so bad execution
windows/brokers can be spotted from the CSV."""
import csv
import os

LOG_PATH = os.path.join("logs", "execution.csv")


def log_execution(symbol, latency_ms, retcode, requoted):
    os.makedirs("logs", exist_ok=True)
    write_header = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["symbol", "latency_ms", "retcode", "requoted"])
        writer.writerow([symbol, round(latency_ms, 1), retcode, requoted])


