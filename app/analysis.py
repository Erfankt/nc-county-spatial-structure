"""Pure-pandas helpers for the NC County Spatial Structure app (no Streamlit imports).

Kept separate from the UI so the logic can be unit-tested and cross-checked against the R pipeline.
"""
from __future__ import annotations

import itertools
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

# Evidence-grade hierarchy (strongest → weakest / unclassifiable)
GRADE_ORDER = ["Robust", "FDR-significant", "Nominal only", "No cluster", "Unreliable estimate"]
GRADE_COLORS = {
    "Robust":              "#b2182b",
    "FDR-significant":     "#ef8a62",
    "Nominal only":        "#fddbc7",
    "No cluster":          "#f0f0f0",
    "Unreliable estimate": "#d9d9d9",
}
GRADE_LABELS = {
    "Robust":              "Robust cluster (FDR + analytic + ≥90 % stable)",
    "FDR-significant":     "FDR-significant cluster",
    "Nominal only":        "Nominally significant (not FDR)",
    "No cluster":          "No spatial cluster",
    "Unreliable estimate": "Estimate too noisy (CV > 40 %)",
}

CV_TIER_COLORS = {
    "Reliable":         "#2166ac",
    "Use with caution": "#f4a582",
    "Unreliable":       "#d6604d",
    "Undetermined":     "#aaaaaa",
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
    if any(tok in name for tok in ("income", "value", "rent")):
        return f"${v:,.0f}"
    if "gini" in name:
        return f"{v:.3f}"
    return f"{v:.1f}"


def cv_tier(estimate: float, moe: float, z: float = 1.645) -> str:
    """ACS coefficient-of-variation tier for a single estimate.

    Returns one of: 'Reliable', 'Use with caution', 'Unreliable', 'Undetermined'.
    """
    try:
        cv = abs(moe / z / estimate)
    except (ZeroDivisionError, TypeError):
        return "Undetermined"
    if np.isnan(cv) or np.isinf(cv):
        return "Undetermined"
    if cv < 0.12:
        return "Reliable"
    if cv < 0.40:
        return "Use with caution"
    return "Unreliable"


def add_cv_tier(df: pd.DataFrame, indicator: str, z: float = 1.645) -> pd.DataFrame:
    """Add a 'cv_tier' column to a county-level DataFrame that already has
    'value' and 'moe' columns for the given indicator."""
    df = df.copy()
    df["cv_tier"] = df.apply(
        lambda r: cv_tier(r.get("value", float("nan")), r.get("moe", float("nan")), z),
        axis=1,
    )
    return df


# ============================================================ derived layers
# Computed in Python from the core CSVs when the R pipeline has not yet
# exported the optional tables (cv_tiers, evidence_grades, correlogram,
# bivariate_lisa).  The app calls these automatically on first load;
# Streamlit's cache_data ensures they run only once per session.

# Indicators to skip in bivariate LISA auto-pairing (log-transformed duplicates of
# their raw counterparts; remove entries here if you want them included).
_BVLISA_EXCLUDE: set[str] = {"log_home_value", "log_med_hh_income"}


def _ind_long(ind: pd.DataFrame) -> pd.DataFrame:
    """Melt wide indicators.csv to long (year, GEOID, NAME, indicator, value, moe)."""
    id_cols = [c for c in ("year", "GEOID", "NAME") if c in ind.columns]
    moe_cols = [c for c in ind.columns if c.endswith("_moe")]
    val_cols = [c for c in ind.columns if c not in id_cols and not c.endswith("_moe")]
    vals = ind.melt(id_vars=id_cols, value_vars=val_cols, var_name="indicator", value_name="value")
    moes = ind.melt(id_vars=["year", "GEOID"], value_vars=moe_cols,
                    var_name="_moe_col", value_name="moe")
    moes["indicator"] = moes["_moe_col"].str[:-4]   # strip "_moe"
    return vals.merge(moes[["year", "GEOID", "indicator", "moe"]],
                      on=["year", "GEOID", "indicator"], how="left")


def _nb_dict(nb: pd.DataFrame) -> dict[str, set[str]]:
    """Build {GEOID: {neighbour GEOIDs}} from a neighbours DataFrame."""
    d: dict[str, set[str]] = {}
    for geoid, grp in nb.groupby("GEOID"):
        d[str(geoid)] = set(grp["neighbor"].astype(str))
    return d


def _kth_order_nb(nb_d: dict[str, set[str]], k: int) -> pd.DataFrame:
    """Return a neighbours DataFrame for exactly the k-th order non-overlapping band.

    k = 1 → immediate queen neighbours (identical to the source data).
    k > 1 → nodes reachable in exactly k steps but not in fewer (BFS).
    """
    if k == 1:
        rows = [(g, n) for g, ns in nb_d.items() for n in ns]
        return pd.DataFrame(rows, columns=["GEOID", "neighbor"])
    rows = []
    for geoid in nb_d:
        seen: set[str] = {geoid}
        frontier: set[str] = {geoid}
        for _ in range(k - 1):
            nxt: set[str] = set()
            for node in frontier:
                nxt |= nb_d.get(node, set()) - seen
            seen |= nxt
            frontier = nxt
        kth: set[str] = set()
        for node in frontier:
            kth |= nb_d.get(node, set()) - seen
        for neighbour in kth:
            rows.append((geoid, neighbour))
    if not rows:
        return pd.DataFrame(columns=["GEOID", "neighbor"])
    return pd.DataFrame(rows, columns=["GEOID", "neighbor"])


def _bh_fdr(p_vals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR correction; returns adjusted p-values clipped to [0, 1]."""
    n = len(p_vals)
    order = np.argsort(p_vals)
    ranked = np.empty(n)
    ranked[order] = np.arange(1, n + 1)
    adj = p_vals * n / ranked
    adj_sorted = adj[order]
    for i in range(n - 2, -1, -1):
        adj_sorted[i] = min(adj_sorted[i], adj_sorted[i + 1])
    result = np.empty(n)
    result[order] = adj_sorted
    return np.clip(result, 0.0, 1.0)


def _bv_quadrant(zx: float, lag_zy: float) -> str:
    if zx > 0 and lag_zy > 0:
        return "High-High"
    if zx < 0 and lag_zy < 0:
        return "Low-Low"
    if zx > 0 and lag_zy <= 0:
        return "High-Low"
    if zx <= 0 and lag_zy > 0:
        return "Low-High"
    return "Not significant"


def _morans_i_perm(
    values: pd.Series,
    nb: pd.DataFrame,
    n_perm: int = 499,
    seed: int = 42,
) -> tuple[float, float, int]:
    """Return (Moran's I, pseudo p-value, n_pairs) via permutation test."""
    if nb.empty:
        return float("nan"), float("nan"), 0
    rng = np.random.default_rng(seed)
    geoid_pos = {g: i for i, g in enumerate(values.index)}
    valid = nb[nb["GEOID"].isin(geoid_pos) & nb["neighbor"].isin(geoid_pos)]
    n_pairs = len(valid)
    if n_pairs == 0:
        return float("nan"), float("nan"), 0
    src = np.array([geoid_pos[g] for g in valid["GEOID"]])
    dst = np.array([geoid_pos[g] for g in valid["neighbor"]])
    n_nb = np.bincount(src, minlength=len(values)).astype(float)
    n_nb[n_nb == 0] = 1.0

    z = (values.values - values.mean())
    z2sum = float((z ** 2).sum())
    if z2sum == 0:
        return 0.0, 1.0, n_pairs

    def _mi(zv: np.ndarray) -> float:
        lag = np.bincount(src, weights=zv[dst], minlength=len(zv)) / n_nb
        return float((zv * lag).sum() / (zv ** 2).sum())

    observed = _mi(z)
    sim = np.array([_mi(rng.permutation(z)) for _ in range(n_perm)])
    p = float((np.abs(sim) >= abs(observed)).sum() + 1) / (n_perm + 1)
    return observed, p, n_pairs


# -------------------------------------------------------------- public API

def compute_cv_tiers(ind: pd.DataFrame) -> pd.DataFrame:
    """Compute CV tiers from wide indicators.csv.

    Returns columns: year, indicator, GEOID, NAME, cv_pct, cv_tier.
    """
    long = _ind_long(ind)
    long["cv_pct"] = (long["moe"].abs() / 1.645 / long["value"].abs() * 100)
    long["cv_tier"] = long.apply(lambda r: cv_tier(r["value"], r["moe"]), axis=1)
    return long[["year", "indicator", "GEOID", "NAME", "cv_pct", "cv_tier"]].copy()


def compute_evidence_grades(
    cv_tiers: pd.DataFrame,
    local: pd.DataFrame,
    stab: pd.DataFrame,
) -> pd.DataFrame:
    """Synthesise evidence grades from CV tiers + local clusters + stability.

    Grade hierarchy (strongest → weakest):
      Robust → FDR-significant → Nominal only → No cluster → Unreliable estimate
    """
    loc = local[["year", "indicator", "GEOID", "NAME", "cluster_raw", "cluster_fdr"]].copy()
    stab_cols = [c for c in ("year", "indicator", "GEOID", "cluster_analytic",
                              "share_draws_same_raw_class") if c in stab.columns]
    merged = loc.merge(cv_tiers[["year", "indicator", "GEOID", "cv_tier"]],
                       on=["year", "indicator", "GEOID"], how="left")
    if len(stab_cols) >= 3:
        merged = merged.merge(stab[stab_cols], on=["year", "indicator", "GEOID"], how="left")
    else:
        merged["cluster_analytic"] = None
        merged["share_draws_same_raw_class"] = float("nan")

    def _grade(row: pd.Series) -> str:
        if row.get("cv_tier") == "Unreliable":
            return "Unreliable estimate"
        fdr_sig = row.get("cluster_fdr", "Not significant") != "Not significant"
        raw_sig = row.get("cluster_raw", "Not significant") != "Not significant"
        analytic_ok = row.get("cluster_analytic") == row.get("cluster_fdr")
        stable = float(row.get("share_draws_same_raw_class") or 0.0) >= 0.9
        if fdr_sig and analytic_ok and stable:
            return "Robust"
        if fdr_sig:
            return "FDR-significant"
        if raw_sig:
            return "Nominal only"
        return "No cluster"

    merged["grade"] = merged.apply(_grade, axis=1)
    keep = ["year", "indicator", "GEOID", "NAME", "cv_tier", "cluster_raw",
            "cluster_fdr", "cluster_analytic", "share_draws_same_raw_class", "grade"]
    return merged[[c for c in keep if c in merged.columns]].copy()


def compute_correlogram(
    ind: pd.DataFrame,
    nb: pd.DataFrame,
    max_lag: int = 5,
    n_perm: int = 499,
) -> pd.DataFrame:
    """Moran's I at queen-contiguity orders 1 .. max_lag (non-overlapping bands).

    Returns columns: year, indicator, order, label, moran_I, p_value, n_pairs.
    """
    long = _ind_long(ind)
    nb_d = _nb_dict(nb)
    rows: list[dict] = []
    for k in range(1, max_lag + 1):
        nb_k = _kth_order_nb(nb_d, k)
        for year, gy in long.groupby("year"):
            for indicator, gi in gy.groupby("indicator"):
                vals = gi.dropna(subset=["value"]).set_index("GEOID")["value"]
                mi, p, n_pairs = _morans_i_perm(vals, nb_k, n_perm=n_perm)
                rows.append({
                    "year": year, "indicator": indicator,
                    "order": k, "label": f"Order {k}",
                    "moran_I": mi, "p_value": p, "n_pairs": n_pairs,
                })
    return pd.DataFrame(rows)


def compute_bivariate_lisa(
    ind: pd.DataFrame,
    nb: pd.DataFrame,
    pairs: list[tuple[str, str]] | None = None,
    n_perm: int = 499,
) -> pd.DataFrame:
    """Bivariate local Moran's I for indicator pairs.

    BV_I_i = z_x[i] * Σ_j w_ij * z_y[j]  (row-standardised weights)
    Permutation test permutes z_y; p-values are BH FDR-adjusted.

    Returns columns: year, x_var, y_var, pair_label, GEOID, NAME,
                     local_I, p_value, p_fdr, quadrant, cluster_raw, cluster_fdr.
    """
    long = _ind_long(ind)
    # Detect available indicator names from the data
    available = sorted(long["indicator"].unique())
    if pairs is None:
        # Auto-generate all unique unordered pairs, excluding log-transformed duplicates
        candidates = [ind for ind in available if ind not in _BVLISA_EXCLUDE]
        pairs = list(itertools.combinations(candidates, 2))
    else:
        avail_set = set(available)
        pairs = [(x, y) for x, y in pairs if x in avail_set and y in avail_set]
    if not pairs:
        return pd.DataFrame(columns=[
            "year", "x_var", "y_var", "pair_label", "GEOID", "NAME",
            "local_I", "p_value", "p_fdr", "quadrant", "cluster_raw", "cluster_fdr"])

    rng = np.random.default_rng(42)
    name_map = (long[["GEOID", "NAME"]].drop_duplicates()
                .set_index("GEOID")["NAME"].to_dict())

    # Build row-standardised weight arrays once (order 1 neighbours)
    all_geoids = sorted(long["GEOID"].unique())
    pos = {g: i for i, g in enumerate(all_geoids)}
    n = len(all_geoids)
    nb_valid = nb[nb["GEOID"].isin(pos) & nb["neighbor"].isin(pos)]
    src = np.array([pos[g] for g in nb_valid["GEOID"]])
    dst = np.array([pos[g] for g in nb_valid["neighbor"]])
    n_nb = np.bincount(src, minlength=n).astype(float)
    n_nb[n_nb == 0] = 1.0

    rows: list[dict] = []
    for year, gy in long.groupby("year"):
        wide = gy.pivot(index="GEOID", columns="indicator", values="value").reindex(all_geoids)

        for x_var, y_var in pairs:
            if x_var not in wide.columns or y_var not in wide.columns:
                continue
            pair_label = f"{x_var} × {y_var}"
            x = wide[x_var].to_numpy(dtype=float, na_value=np.nan)
            y = wide[y_var].to_numpy(dtype=float, na_value=np.nan)
            valid = ~(np.isnan(x) | np.isnan(y))
            if valid.sum() < 10:
                continue

            xm, xs = x[valid].mean(), x[valid].std(ddof=1)
            ym, ys = y[valid].mean(), y[valid].std(ddof=1)
            zx = np.where(valid, (x - xm) / (xs or 1.0), 0.0)
            zy = np.where(valid, (y - ym) / (ys or 1.0), 0.0)

            def _bv_local(zy_v: np.ndarray) -> np.ndarray:
                lag = np.bincount(src, weights=zy_v[dst], minlength=n) / n_nb
                return zx * lag

            obs = _bv_local(zy)
            sim = np.column_stack([_bv_local(rng.permutation(zy)) for _ in range(n_perm)])
            p_vals = ((np.abs(sim) >= np.abs(obs[:, None])).sum(axis=1) + 1) / (n_perm + 1)
            p_fdr = _bh_fdr(p_vals)

            lag_zy_obs = np.bincount(src, weights=zy[dst], minlength=n) / n_nb
            for i, geoid in enumerate(all_geoids):
                if not valid[i]:
                    continue
                li = float(obs[i])
                p = float(p_vals[i])
                pf = float(p_fdr[i])
                q = _bv_quadrant(float(zx[i]), float(lag_zy_obs[i]))
                rows.append({
                    "year": year, "x_var": x_var, "y_var": y_var,
                    "pair_label": pair_label, "GEOID": geoid,
                    "NAME": name_map.get(geoid, ""),
                    "local_I": li, "p_value": p, "p_fdr": pf,
                    "quadrant": q,
                    "cluster_raw": q if p < 0.05 else "Not significant",
                    "cluster_fdr": q if pf < 0.05 else "Not significant",
                })
    return pd.DataFrame(rows)
