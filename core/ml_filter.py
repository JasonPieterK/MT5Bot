"""Lightweight logistic-regression win-probability filter, trained on the bot's own
closed-deal history. Deliberately small feature set — MT5's retail deal history has
no sl/tp/entry stored on the deal itself, so reward:risk can't be reconstructed after
the fact, and the API exposes no order-book data. Features used are only what's
actually available: which strategy, hour of day, day of week."""
import json
import os

import numpy as np

WEIGHTS_PATH = os.path.join("logs", "ml_weights.json")
STRATEGY_IDS = {"trend": 0, "scalping": 1, "smc": 2, "grid": 3, "pivot_breakout": 4}


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def build_features(strategy_name, hour, weekday):
    strategy_id = STRATEGY_IDS.get(strategy_name, 0)
    return np.array([1.0, strategy_id / len(STRATEGY_IDS), hour / 24.0, weekday / 7.0])


def train(feature_rows, labels, lr=0.1, epochs=500):
    x = np.array(feature_rows, dtype=float)
    y = np.array(labels, dtype=float)
    weights = np.zeros(x.shape[1])
    n = len(y)
    for _ in range(epochs):
        preds = _sigmoid(x @ weights)
        gradient = x.T @ (preds - y) / n
        weights -= lr * gradient
    return weights


def predict_proba(weights, features):
    return float(_sigmoid(np.dot(weights, features)))


def save_weights(weights):
    os.makedirs(os.path.dirname(WEIGHTS_PATH), exist_ok=True)
    with open(WEIGHTS_PATH, "w") as f:
        json.dump(list(weights), f)


def load_weights():
    if not os.path.exists(WEIGHTS_PATH):
        return None
    with open(WEIGHTS_PATH, "r") as f:
        return np.array(json.load(f))
