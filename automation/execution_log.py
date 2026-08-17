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


def summarize(rows):
    """rows: list of dicts with symbol/latency_ms/requoted, as read back from the CSV."""
    per_symbol = {}
    for row in rows:
        symbol = row["symbol"]
        stats = per_symbol.setdefault(symbol, {"count": 0, "requotes": 0, "total_latency_ms": 0.0})
        stats["count"] += 1
        stats["total_latency_ms"] += float(row["latency_ms"])
        if str(row["requoted"]).lower() == "true":
            stats["requotes"] += 1
    for symbol, stats in per_symbol.items():
        stats["avg_latency_ms"] = round(stats["total_latency_ms"] / stats["count"], 1)
        stats["requote_rate_percent"] = round(stats["requotes"] / stats["count"] * 100, 1)
    return per_symbol
