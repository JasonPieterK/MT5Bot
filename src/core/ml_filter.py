"""Lightweight logistic-regression win-probability filter, trained on the bot's own
closed-deal history.

Deliberately small feature set: MT5's retail deal history stores no sl/tp/entry on the deal
itself, so reward:risk cannot be reconstructed after the fact, and the API exposes no
order-book data. What is actually available is which strategy placed the trade, the hour of
day and the day of week -- and richer feature sets built from the same rows were measured
and made out-of-sample performance strictly WORSE (in-sample AUC 0.995, out-of-sample 0.27),
which is what overfitting looks like on a few hundred rows.

Because of that, every model here is judged out-of-sample on a time-ordered split before it
is allowed to exist. `train_and_evaluate` refuses to return a model whose out-of-sample
discrimination is no better than chance. A filter that cannot beat a coin flip does not
merely fail to help -- it adds confidence that is not there, which is worse than no filter.

Also note what the label means. It is "this trade closed positive", not "this trade made
money on balance". On real history a 84%-win-rate strategy lost $5.7M, so a model that
maximises win probability can happily select the trades that lose the most. Treat a passing
model as a weak prior, never as permission."""
import json
import os

import numpy as np

WEIGHTS_PATH = os.path.join("logs", "ml_weights.json")
# "unknown" covers deals whose magic number belongs to no strategy of this bot -- hand
# trades, another EA, an older version. Dropping them silently is how a training run on
# 1,079 real closed trades ended up with zero rows and no explanation.
STRATEGY_IDS = {"trend": 0, "scalping": 1, "smc": 2, "grid": 3, "pivot_breakout": 4,
                "ensemble": 5, "unknown": 6}

# Out-of-sample AUC a model must clear to be worth saving. 0.5 is a coin flip; 0.55 is a
# deliberately low bar that this account's own history still does not come close to meeting.
MIN_OOS_AUC = 0.55
# Below this many test rows the AUC is noise, whatever it says.
MIN_TEST_ROWS = 30
# A filter has to filter. On this account's real history the model scores a respectable
# out-of-sample AUC of 0.65 and then passes 324 out of 324 held-out trades -- it ranks
# trades in roughly the right order but its probabilities never cross the threshold, so
# enabling it changes nothing while looking like a working safeguard. AUC alone would have
# shipped that.
DECISION_THRESHOLD = 0.5
MIN_REJECT_FRACTION = 0.05


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


def auc(labels, probabilities):
    """Area under the ROC curve: the chance a randomly chosen winner is scored above a
    randomly chosen loser. 0.5 is a coin flip. Returns None when one class is missing, which
    on this kind of data is common and must not be reported as a good score."""
    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    positives, negatives = y.sum(), (1 - y).sum()
    if positives == 0 or negatives == 0 or len(y) == 0:
        return None
    # Tied scores must share the average rank. Without that a model that outputs the same
    # probability for every trade -- the exact degenerate case this data produces -- scores
    # a perfect 1.0 and gets shipped.
    order = np.argsort(p, kind="mergesort")
    sorted_p = p[order]
    ranks = np.empty(len(y), dtype=float)
    i = 0
    while i < len(sorted_p):
        j = i
        while j + 1 < len(sorted_p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j + 2) / 2.0  # 1-based average of the tied block
        i = j + 1
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def train_and_evaluate(feature_rows, labels, split=0.7, lr=0.5, epochs=3000,
                        threshold=DECISION_THRESHOLD):
    """Fit on the first `split` of the rows in time order, score the rest, and only hand
    back weights that earned it.

    Time-ordered, never shuffled: shuffling leaks the future into the training set and turns
    a worthless model into an impressive-looking one.

    `threshold` must be the probability floor the filter will actually run at
    (global_settings["ml_filter_min_probability"]); validating at a different one measures a
    different filter than the one that will be making decisions.

    Returns (weights_or_None, report)."""
    x = np.array(feature_rows, dtype=float)
    y = np.array(labels, dtype=float)
    cut = int(len(y) * split)
    report = {"rows": len(y), "train_rows": cut, "test_rows": len(y) - cut,
              "base_rate_train": float(y[:cut].mean()) if cut else 0.0,
              "base_rate_test": float(y[cut:].mean()) if len(y) - cut else 0.0,
              "in_sample_auc": None, "out_of_sample_auc": None,
              "out_of_sample_accuracy": None, "test_passed": 0, "test_rejected": 0,
              "win_rate_passed": None, "win_rate_rejected": None,
              "threshold": threshold, "accepted": False, "reason": ""}

    if report["test_rows"] < MIN_TEST_ROWS:
        report["reason"] = (f"only {report['test_rows']} trades left for out-of-sample "
                            f"testing, need {MIN_TEST_ROWS}. Nothing can be validated on that.")
        return None, report

    weights = train(x[:cut], y[:cut], lr=lr, epochs=epochs)
    in_sample = _sigmoid(x[:cut] @ weights)
    out_sample = _sigmoid(x[cut:] @ weights)
    report["in_sample_auc"] = auc(y[:cut], in_sample)
    report["out_of_sample_auc"] = auc(y[cut:], out_sample)
    report["out_of_sample_accuracy"] = float(
        ((out_sample >= threshold).astype(float) == y[cut:]).mean())

    test_y = y[cut:]
    passes = out_sample >= threshold
    report["test_passed"] = int(passes.sum())
    report["test_rejected"] = int((~passes).sum())
    report["win_rate_passed"] = float(test_y[passes].mean()) if passes.any() else None
    report["win_rate_rejected"] = float(test_y[~passes].mean()) if (~passes).any() else None

    if report["out_of_sample_auc"] is None:
        report["reason"] = ("every out-of-sample trade had the same outcome, so there is "
                            "nothing to measure discrimination against.")
        return None, report
    if report["out_of_sample_auc"] < MIN_OOS_AUC:
        report["reason"] = (f"out-of-sample AUC {report['out_of_sample_auc']:.3f} does not beat "
                            f"the {MIN_OOS_AUC} minimum (0.5 is a coin flip). This history does "
                            f"not contain a pattern the filter can learn.")
        return None, report
    if report["test_rejected"] < MIN_REJECT_FRACTION * report["test_rows"]:
        report["reason"] = (
            f"the model passes {report['test_passed']} of {report['test_rows']} held-out "
            f"trades, so turning it on would change almost nothing while looking like a "
            f"working filter. Its ranking may be fine (AUC "
            f"{report['out_of_sample_auc']:.3f}), but its probabilities never fall below "
            f"the {threshold} threshold it will run at.")
        return None, report
    if (report["win_rate_rejected"] is not None
            and report["win_rate_passed"] is not None
            and report["win_rate_passed"] <= report["win_rate_rejected"]):
        report["reason"] = (
            f"out of sample the trades this model passes win "
            f"{report['win_rate_passed'] * 100:.1f}% of the time and the ones it rejects win "
            f"{report['win_rate_rejected'] * 100:.1f}% — it is filtering the wrong way round.")
        return None, report

    report["accepted"] = True
    # Refit on everything once it has proved itself out of sample: the validated model was
    # fit on 70% of the data, and there is no reason to ship the weaker one.
    return train(x, y, lr=lr, epochs=epochs), report
