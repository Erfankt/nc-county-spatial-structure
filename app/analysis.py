"""Pure-pandas helpers for the NC County Spatial Structure app (no Streamlit imports).

Kept separate from the UI so the logic can be unit-tested and cross-checked against the R pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

CLUSTER_ORDER = ["High-High", "Low-Low", "High-Low", "Low-High", "Not significant"]
CLUSTER_COLORS = {
    "High-High": "#b2182b",
    "Low-Low": "#2166ac",
    "High-Low": "#ef8a62",
    "Low-High": "#67a9cf",
    "Not significant": "#d9d9d9",
}
WINDOW_LABELS = {2012: "2008-2012", 2017: "2013-2017", 2022: "2018-2022"}
TERM_LABELS = {
    "(Intercept)": "Intercept",
    "ba_plus_rate_z": "Bachelor's degree or higher",
    "unemp_rate_z": "Unemployment rate",
    "med_age_z": "Median age",
    "log_pop_z": "Population (log)",
    "log_home_value_z": "Median home value (log)",
}


# ---------------------------------------------------------------- loading
def read_csv(name: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return pd.read_csv(data_dir / name, dtype={"GEOID": str, "neighbor": str})


def read_geojson(data_dir: Path = DATA_DIR) -> dict:
    with open(data_dir / "counties.geojson", encoding="utf-8") as f:
        return json.load(f)


def read_meta(data_dir: Path = DATA_DIR) -> dict:
    with open(data_dir / "metadata.json", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------- spatial statistics
def neighbor_lag(values: pd.Series, neighbors: pd.DataFrame) -> pd.Series:
    """Row-standardised spatial lag: the mean of each unit's neighbours' values.

    `values` is indexed by GEOID; `neighbors` has columns GEOID, neighbor (queen contiguity).
    """
    nb = neighbors.assign(nb_value=neighbors["neighbor"].map(values))
    lag = nb.groupby("GEOID")["nb_value"].mean()
    return lag.reindex(values.index).fillna(0.0)


def morans_i(values: pd.Series, neighbors: pd.DataFrame) -> float:
    """Global Moran's I with row-standardised weights (S0 = n, so I = sum(z * lag) / sum(z^2))."""
    z = values - values.mean()
    lag = neighbor_lag(z, neighbors)
    return float((z * lag).sum() / (z ** 2).sum())


def moran_scatter(values: pd.Series, neighbors: pd.DataFrame) -> pd.DataFrame:
    """Standardised value and its spatial lag for a Moran scatterplot."""
    z = (values - values.mean()) / values.std(ddof=1)
    return pd.DataFrame({"z": z, "lag_z": neighbor_lag(z, neighbors)}).rename_axis("GEOID").reset_index()


# ------------------------------------------------------------ result logic
def robust_clusters(stab: pd.DataFrame, min_stability: float = 0.9) -> pd.DataFrame:
    """Clusters passing all three checks: FDR-significant, same label under the analytic test,
    and stable (>= min_stability) under margin-of-error resampling."""
    sig = stab[stab["cluster_headline_fdr"] != "Not significant"].copy()
    sig["passes_fdr"] = True
    sig["passes_analytic"] = sig["cluster_analytic"] == sig["cluster_headline_fdr"]
    sig["passes_stability"] = sig["share_draws_same_raw_class"] >= min_stability
    sig["robust"] = sig[["passes_fdr", "passes_analytic", "passes_stability"]].all(axis=1)
    return sig


def fmt_value(v: float, is_rate: bool, name: str = "") -> str:
    if pd.isna(v):
        return "n/a"
    if is_rate:
        return f"{100 * v:.1f}%"
    if "income" in name or "value" in name:
        return f"${v:,.0f}"
    return f"{v:.1f}"
