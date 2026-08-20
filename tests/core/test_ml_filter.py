import numpy as np
import core.ml_filter as ml_filter


def test_build_features_shape():
    features = ml_filter.build_features("trend", hour=10, weekday=2)
    assert len(features) == 4
    assert features[0] == 1.0


def test_train_separable_data_predicts_correctly():
    # feature 1 alone determines the label; model should learn a strong weight on it
    features = [[1.0, 1.0, 0.0, 0.0]] * 20 + [[1.0, 0.0, 0.0, 0.0]] * 20
    labels = [1] * 20 + [0] * 20
    weights = ml_filter.train(features, labels, lr=0.5, epochs=1000)
    high_proba = ml_filter.predict_proba(weights, [1.0, 1.0, 0.0, 0.0])
    low_proba = ml_filter.predict_proba(weights, [1.0, 0.0, 0.0, 0.0])
    assert high_proba > 0.7
    assert low_proba < 0.3


def test_predict_proba_between_zero_and_one():
    weights = np.array([0.1, 0.2, 0.3, 0.4])
    proba = ml_filter.predict_proba(weights, [1.0, 0.5, 0.5, 0.5])
    assert 0 <= proba <= 1


def test_save_and_load_weights_round_trip(tmp_path, monkeypatch):
    path = str(tmp_path / "ml_weights.json")
    monkeypatch.setattr(ml_filter, "WEIGHTS_PATH", path)
    weights = np.array([0.1, -0.2, 0.3, 0.05])
    ml_filter.save_weights(weights)
    loaded = ml_filter.load_weights()
    assert np.allclose(loaded, weights)


def test_load_weights_returns_none_when_missing(tmp_path, monkeypatch):
    path = str(tmp_path / "ml_weights.json")
    monkeypatch.setattr(ml_filter, "WEIGHTS_PATH", path)
    assert ml_filter.load_weights() is None


# --- out-of-sample discipline -------------------------------------------------
# The real reason these exist: on this account's 1,079 closed trades the filter's
# out-of-sample AUC is at or below 0.5, and richer features made it worse, not better.
# A model that cannot beat a coin flip must never reach logs/ml_weights.json.

def learnable(n=300):
    features, labels = [], []
    for i in range(n):
        hour = i % 24
        features.append(ml_filter.build_features("trend", hour, i % 7))
        labels.append(1 if hour < 12 else 0)
    return features, labels


def noise(n=300, seed=3):
    import random
    rng = random.Random(seed)
    features, labels = [], []
    for i in range(n):
        features.append(ml_filter.build_features("trend", i % 24, i % 7))
        labels.append(rng.randint(0, 1))
    return features, labels


def test_auc_is_half_for_a_coin_flip_and_one_for_a_perfect_ranker():
    labels = [0, 0, 1, 1]
    assert ml_filter.auc(labels, [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert ml_filter.auc(labels, [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert ml_filter.auc(labels, [0.5, 0.5, 0.5, 0.5]) == 0.5


def test_auc_is_none_when_one_class_is_missing():
    # Five of seven walk-forward folds on the real data had a 100% win rate. Reporting a
    # number there would be reporting noise as skill.
    assert ml_filter.auc([1, 1, 1], [0.1, 0.5, 0.9]) is None


def test_a_real_pattern_is_learned_and_accepted():
    weights, report = ml_filter.train_and_evaluate(*learnable())
    assert weights is not None
    assert report["accepted"] is True
    assert report["out_of_sample_auc"] >= ml_filter.MIN_OOS_AUC


def test_pure_noise_is_rejected_not_shipped():
    weights, report = ml_filter.train_and_evaluate(*noise())
    assert weights is None
    assert report["accepted"] is False
    assert report["out_of_sample_auc"] is not None
    assert "coin flip" in report["reason"]


def test_too_few_test_rows_is_rejected_however_good_it_looks():
    features, labels = learnable(n=40)
    weights, report = ml_filter.train_and_evaluate(features, labels)
    assert weights is None
    assert "out-of-sample" in report["reason"]


def test_evaluation_split_is_by_time_never_shuffled():
    # Shuffling leaks the future into the training set. If the split were random, a series
    # whose second half is unlearnable from its first half would still score well.
    features = [ml_filter.build_features("trend", i % 24, 0) for i in range(300)]
    labels = [1 if i < 210 else 0 for i in range(300)]   # regime changes at the split
    weights, report = ml_filter.train_and_evaluate(features, labels, split=0.7)
    assert weights is None
    assert report["base_rate_train"] == 1.0
    assert report["base_rate_test"] == 0.0


def test_training_is_reproducible():
    features, labels = learnable()
    first, _ = ml_filter.train_and_evaluate(features, labels)
    second, _ = ml_filter.train_and_evaluate(features, labels)
    assert np.allclose(first, second)


def test_unknown_strategy_has_its_own_feature_id():
    # Every real closed trade on this account has a magic belonging to no strategy here.
    assert "unknown" in ml_filter.STRATEGY_IDS
    assert (ml_filter.build_features("unknown", 0, 0)
            != ml_filter.build_features("trend", 0, 0)).any()


def test_a_constant_predictor_scores_exactly_chance():
    # The degenerate model this account's data actually produces: same probability for
    # every trade. Without tie-aware ranking it scores a perfect 1.0 and gets shipped.
    labels = [0, 1] * 50
    assert ml_filter.auc(labels, [0.84] * 100) == 0.5


def test_a_model_that_passes_everything_is_rejected():
    """The real trap. On this account's history the model earns an out-of-sample AUC of
    0.65 and then passes 324 of 324 held-out trades: it ranks trades sensibly but never
    actually says no. Enabling it would change nothing while looking like a safeguard."""
    features, labels = [], []
    for i in range(300):
        features.append(ml_filter.build_features("trend", i % 24, i % 7))
        # Nearly all winners: the fitted probabilities all sit above the threshold.
        labels.append(0 if i % 24 == 0 else 1)
    weights, report = ml_filter.train_and_evaluate(features, labels)
    assert report["test_passed"] == report["test_rows"]
    assert weights is None
    assert "change almost nothing" in report["reason"]


def test_validation_uses_the_threshold_the_filter_will_run_at():
    features, labels = [], []
    for i in range(300):
        features.append(ml_filter.build_features("trend", i % 24, i % 7))
        labels.append(0 if i % 24 == 0 else 1)
    # At 0.5 the model never says no, so it is refused as inert...
    _, lax = ml_filter.train_and_evaluate(features, labels, threshold=0.5)
    assert lax["test_rejected"] == 0
    # ...and a stricter floor is a genuinely different filter, so it is measured as one.
    _, strict = ml_filter.train_and_evaluate(features, labels, threshold=0.97)
    assert strict["threshold"] == 0.97
    assert strict["test_rejected"] > lax["test_rejected"]
