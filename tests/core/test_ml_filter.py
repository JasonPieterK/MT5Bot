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
