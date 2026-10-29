"""Unit tests for app/analysis.py (pure pandas, no Streamlit)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import analysis as an  # noqa: E402


def line_graph():
    """Four units in a line: A - B - C - D."""
    return pd.DataFrame({
        "GEOID": ["A", "B", "B", "C", "C", "D"],
        "neighbor": ["B", "A", "C", "B", "D", "C"],
    })


def test_neighbor_lag_is_mean_of_neighbours():
    v = pd.Series({"A": 1.0, "B": 2.0, "C": 4.0, "D": 8.0})
    lag = an.neighbor_lag(v, line_graph())
    assert lag["A"] == 2.0                 # only neighbour B
    assert lag["B"] == pytest.approx(2.5)  # mean of A and C
    assert lag["C"] == pytest.approx(5.0)  # mean of B and D
    assert lag["D"] == 4.0


def test_morans_i_matches_hand_calculation():
    v = pd.Series({"A": 1.0, "B": 2.0, "C": 4.0, "D": 8.0})
    z = v - v.mean()
    lag = an.neighbor_lag(z, line_graph())
    expected = (z * lag).sum() / (z ** 2).sum()
    assert an.morans_i(v, line_graph()) == pytest.approx(expected)
    assert an.morans_i(v, line_graph()) > 0   # a monotone gradient is positively autocorrelated


def test_morans_i_negative_for_alternating_values():
    v = pd.Series({"A": 1.0, "B": -1.0, "C": 1.0, "D": -1.0})
    assert an.morans_i(v, line_graph()) < 0


def test_moran_scatter_standardises():
    v = pd.Series({"A": 1.0, "B": 2.0, "C": 4.0, "D": 8.0})
    sc = an.moran_scatter(v, line_graph())
    assert sc["z"].mean() == pytest.approx(0, abs=1e-12)
    assert sc["z"].std(ddof=1) == pytest.approx(1)


def test_robust_clusters_requires_all_three_checks():
    stab = pd.DataFrame({
        "indicator": ["x"] * 4,
        "NAME": ["a", "b", "c", "d"],
        "cluster_headline_fdr": ["High-High", "High-High", "Low-Low", "Not significant"],
        "cluster_analytic": ["High-High", "Not significant", "Low-Low", "Not significant"],
        "share_draws_same_raw_class": [0.99, 1.0, 0.5, 1.0],
    })
    out = an.robust_clusters(stab).set_index("NAME")
    assert list(out.index) == ["a", "b", "c"]                 # unflagged county d is excluded
    assert out.loc["a", "robust"]                              # passes all three
    assert not out.loc["b", "robust"]                          # fails the analytic test
    assert not out.loc["c", "robust"]                          # fails stability


def test_fmt_value():
    assert an.fmt_value(0.1234, True) == "12.3%"
    assert an.fmt_value(55000, False, "med_hh_income") == "$55,000"
    assert an.fmt_value(41.26, False, "med_age") == "41.3"
    assert an.fmt_value(float("nan"), True) == "n/a"
