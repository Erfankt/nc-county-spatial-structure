"""NC County Spatial Structure explorer.

Reads the result files written by the R pipeline (app/data/) and lets you explore where North Carolina
counties cluster, how that changed between ACS windows, and how much of it survives ACS sampling error.
Run locally:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analysis as an

st.set_page_config(page_title="NC County Spatial Structure", page_icon=None, layout="wide")


# ------------------------------------------------------------------ data
@st.cache_data
def load_all():
    d = {
        "geo": an.read_geojson(),
        "meta": an.read_meta(),
    }
    for key, f in {
        "ind": "indicators.csv", "local": "local_clusters.csv", "glob": "global_moran.csv",
        "sens": "weights_sensitivity.csv", "persist": "cluster_persistence.csv",
        "stab": "stability_county.csv", "moe_glob": "moe_global_moran.csv",
        "moe_sum": "acs_moe_summary.csv", "agree": "perm_vs_analytic_agreement.csv",
        "mcomp": "model_comparison.csv", "mdiag": "model_diagnostics.csv",
        "mcoef": "model_coefficients.csv", "mres": "model_ols_residuals.csv",
        "nb": "neighbors.csv",
    }.items():
        d[key] = an.read_csv(f)
    # Build a dict of available residuals: {model_label: DataFrame}
    _resid_files = {
        "OLS":       "model_ols_residuals.csv",
        "SAR lag":   "model_sar_lag_residuals.csv",
        "SEM error": "model_sem_error_residuals.csv",
        "SDM":       "model_sdm_residuals.csv",
    }
    d["resid_map"] = {"OLS": d["mres"]}  # OLS always present
    for label, fname in _resid_files.items():
        if label == "OLS":
            continue
        p = an.DATA_DIR / fname
        if p.exists():
            try:
                d["resid_map"][label] = an.read_csv(fname)
            except Exception:
                pass
    # Analytical layers: prefer R pipeline CSVs when present (fast, high-perm);
    # fall back to Python computation from core CSVs automatically.
    def _load_or_compute(filename: str, compute):
        try:
            p = an.DATA_DIR / filename
            return an.read_csv(filename) if p.exists() else compute()
        except Exception:
            return None

    d["cv_tiers"] = _load_or_compute(
        "cv_tiers.csv", lambda: an.compute_cv_tiers(d["ind"]))
    d["evidence"] = _load_or_compute(
        "evidence_grades.csv",
        lambda: an.compute_evidence_grades(d["cv_tiers"], d["local"], d["stab"]))
    d["corro"] = _load_or_compute(
        "correlogram.csv", lambda: an.compute_correlogram(d["ind"], d["nb"]))
    d["bvlisa"] = _load_or_compute(
        "bivariate_lisa.csv", lambda: an.compute_bivariate_lisa(d["ind"], d["nb"]))
    return d


D = load_all()
META = D["meta"]
ind_df = pd.DataFrame(META["indicators"])
LABEL = dict(zip(ind_df["name"], ind_df["label"]))
IS_RATE = dict(zip(ind_df["name"], ind_df["is_rate"]))
WINDOWS = [int(y) for y in META["acs_windows"]]
LATEST = max(WINDOWS)
P = META["parameters"]


def window(y: int) -> str:
    return f"{an.WINDOW_LABELS.get(y, str(y))} (ACS {y})"


# --------------------------------------------------------------- sidebar
st.sidebar.title("NC County Spatial Structure")
st.sidebar.caption("100 counties, ACS 5-year estimates")
indicator = st.sidebar.selectbox("Indicator", list(LABEL), format_func=LABEL.get)
year = st.sidebar.radio("ACS window", WINDOWS, index=len(WINDOWS) - 1, format_func=window)
_view_opts = (["Evidence grade"] if D["evidence"] is not None else []) + \
    ["Values", "Clusters (FDR-adjusted)", "Clusters (unadjusted)"]
view = st.sidebar.radio("Map shows", _view_opts)
st.sidebar.markdown("---")
st.sidebar.caption(
    f"Built {META['built_at']}. {P['n_permutations']:,} permutations, seed {P['seed']}. "
    "Data: U.S. Census Bureau, American Community Survey."
)


# ------------------------------------------------- refresh data (local only)
def _find_rscript() -> str | None:
    """Locate Rscript: PATH first, then common Windows install folders."""
    exe = shutil.which("Rscript")
    if exe:
        return exe
    candidates = sorted(glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe")) + \
        sorted(glob.glob(r"C:\Program Files (x86)\R\R-*\bin\Rscript.exe"))
    return candidates[-1] if candidates else None


with st.sidebar.expander("Refresh Census data"):
    st.caption(
        "Re-pulls every ACS variable from the Census API and rebuilds all files in "
        "app/data/. Local only \u2014 needs R installed on this machine; a Streamlit "
        "Community Cloud deployment has no R runtime, so this control won't work there."
    )
    _repo_root = an.DATA_DIR.parent.parent  # app/data -> app -> repo root
    _auto_rscript = _find_rscript()
    rscript_path = _auto_rscript or st.text_input(
        "Rscript.exe path (not found automatically)",
        placeholder=r"C:\Program Files\R\R-4.4.1\bin\Rscript.exe",
        key="rscript_path_input",
    )
    api_key = st.text_input(
        "Census API key", type="password",
        value=os.environ.get("CENSUS_API_KEY", ""),
        help="Free key: https://api.census.gov/data/key_signup.html. "
             "Used only for this run, never written to disk or logged.",
        key="census_api_key_input",
    )
    confirm = st.checkbox(
        "I understand this calls the Census API and can take 10\u201330 minutes "
        "(153 indicator pairs \u00d7 3 ACS windows for bivariate LISA alone)"
    )
    if st.button("Run pipeline now", disabled=not (rscript_path and api_key and confirm)):
        env = os.environ.copy()
        env["CENSUS_API_KEY"] = api_key
        log_lines: list[str] = []
        log_box = st.empty()
        log_box.code("Starting pipeline/run_all.R ...")
        try:
            proc = subprocess.Popen(
                [rscript_path, "pipeline/run_all.R"],
                cwd=str(_repo_root), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                log_lines.append(line.rstrip("\n"))
                log_box.code("\n".join(log_lines[-200:]) or "(no output yet)")
            proc.wait()
        except FileNotFoundError:
            st.error(f"Couldn't run '{rscript_path}' \u2014 check the path above.")
        else:
            if proc.returncode == 0:
                st.success("Pipeline finished. Reloading data\u2026")
                load_all.clear()
                st.rerun()
            else:
                st.error(f"Pipeline exited with code {proc.returncode}. See the log above.")

# ------------------------------------------------------------- tabs
st.title("Where do North Carolina counties cluster, and how much of it is real?")
st.caption(
    "Spatial autocorrelation of county socioeconomic indicators, with multiple-testing correction and "
    "a check against ACS sampling error."
)
tab_map, tab_time, tab_rob, tab_model, tab_about = st.tabs(
    ["Map explorer", "Trends", "Robustness", "Models", "Method and caveats"]
)

local = D["local"]
stab_all = D["stab"]
rob_all = an.robust_clusters(stab_all)
stab = stab_all[stab_all["year"] == LATEST]   # headline numbers use the latest window
rob = rob_all[rob_all["year"] == LATEST]

# ------------------------------------------------------------ map explorer
with tab_map:
    sub = local[(local["indicator"] == indicator) & (local["year"] == year)].copy()
    ind_y = D["ind"][D["ind"]["year"] == year].set_index("GEOID")
    sub["moe"] = sub["GEOID"].map(ind_y[f"{indicator}_moe"])
    sub["Estimate"] = [an.fmt_value(v, IS_RATE[indicator], indicator) for v in sub["value"]]
    sub["Margin of error (90%)"] = [an.fmt_value(v, IS_RATE[indicator], indicator) for v in sub["moe"]]
    sub["FDR p"] = sub["p_fdr"].round(3)
    cl_col = "cluster_fdr" if view == "Clusters (FDR-adjusted)" else "cluster_raw"
    center = {"lat": 35.2, "lon": -79.6}
    hover = {"GEOID": False, "Estimate": True, "Margin of error (90%)": True, "FDR p": True}

    if view == "Evidence grade" and D["evidence"] is not None:
        ev = D["evidence"][(D["evidence"]["indicator"] == indicator) & (D["evidence"]["year"] == year)][
            ["GEOID", "grade"]].copy()
        sub = sub.merge(ev, on="GEOID", how="left")
        sub["Grade"] = pd.Categorical(sub["grade"], categories=an.GRADE_ORDER, ordered=True)
        hover_eg = {**hover, "Grade": True}
        fig = px.choropleth_map(
            sub, geojson=D["geo"], locations="GEOID", featureidkey="properties.GEOID", color="Grade",
            color_discrete_map=an.GRADE_COLORS, category_orders={"Grade": an.GRADE_ORDER},
            hover_name="NAME", hover_data=hover_eg, map_style="white-bg", center=center, zoom=5.15, opacity=0.85)
    elif view == "Values":
        fig = px.choropleth_map(
            sub, geojson=D["geo"], locations="GEOID", featureidkey="properties.GEOID", color="value",
            color_continuous_scale="Viridis", hover_name="NAME", hover_data=hover, map_style="white-bg",
            center=center, zoom=5.15, opacity=0.8, labels={"value": LABEL[indicator]})
        fig.update_coloraxes(colorbar=dict(orientation="h", y=-0.02, thickness=12, len=0.6,
                                           title=dict(text=""), **({"tickformat": ".0%"} if IS_RATE[indicator] else {})))
    else:
        sub["Cluster"] = sub[cl_col]
        hover["Cluster"] = True
        fig = px.choropleth_map(
            sub, geojson=D["geo"], locations="GEOID", featureidkey="properties.GEOID", color="Cluster",
            color_discrete_map=an.CLUSTER_COLORS, category_orders={"Cluster": an.CLUSTER_ORDER},
            hover_name="NAME", hover_data=hover, map_style="white-bg", center=center, zoom=5.15, opacity=0.85)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=400, legend=dict(orientation="h", y=-0.02))
    left, right = st.columns([3, 2])
    with left:
        st.subheader(f"{LABEL[indicator]}, {window(year)}")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Moran scatterplot")
        vals = sub.set_index("GEOID")["value"]
        sc = an.moran_scatter(vals, D["nb"]).merge(sub[["GEOID", "NAME", cl_col]], on="GEOID")
        is_cluster_view = view not in ("Values", "Evidence grade")
        sc = sc.rename(columns={cl_col: "Cluster"}) if is_cluster_view else sc.assign(Cluster="Not significant")
        sfig = px.scatter(sc, x="z", y="lag_z", color="Cluster", hover_name="NAME",
                          color_discrete_map=an.CLUSTER_COLORS, category_orders={"Cluster": an.CLUSTER_ORDER},
                          labels={"z": "Standardised value", "lag_z": "Neighbour average"})
        sfig.add_hline(y=0, line_color="grey"); sfig.add_vline(x=0, line_color="grey")
        sfig.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0), showlegend=is_cluster_view)
        st.plotly_chart(sfig, use_container_width=True)
        gi = an.morans_i(vals, D["nb"])

    if D["bvlisa"] is not None:
        with st.expander("Bivariate LISA — spatial co-clustering of indicator pairs"):
            bv = D["bvlisa"][D["bvlisa"]["year"] == year]
            bv_pairs = sorted(bv["pair_label"].unique().tolist())
            if len(bv_pairs):
                sel_pair = st.selectbox("Indicator pair", bv_pairs, key="bv_pair")
                bv_sub = bv[bv["pair_label"] == sel_pair].copy()
                bv_sub["Cluster"] = bv_sub["cluster_fdr"]
                bvfig = px.choropleth_map(
                    bv_sub, geojson=D["geo"], locations="GEOID", featureidkey="properties.GEOID", color="Cluster",
                    color_discrete_map=an.CLUSTER_COLORS, category_orders={"Cluster": an.CLUSTER_ORDER},
                    hover_name="NAME", hover_data={"GEOID": False, "cluster_fdr": True},
                    map_style="white-bg", center=center, zoom=5.15, opacity=0.85)
                bvfig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=370,
                                    legend=dict(orientation="h", y=-0.02))
                st.plotly_chart(bvfig, use_container_width=True)
                st.caption(
                    "Each county's *focal* indicator value is compared against its neighbours' *lagged* indicator value. "
                    "High-High means the focal county has a high focal value and its neighbours have high lagged values. "
                    "p-values are FDR-adjusted (BH) across 100 counties."
                )
            else:
                st.info("Bivariate LISA results not available for the selected window.")

# --------------------------------------------------------------- trends
with tab_time:
    st.subheader("Global Moran's I by ACS window")
    trend_inds = st.multiselect(
        "Indicators",
        options=list(LABEL),
        default=list(LABEL),
        format_func=LABEL.get,
        key="trend_ind_filter",
    )
    if not trend_inds:
        trend_inds = list(LABEL)
    g = D["glob"].assign(Indicator=lambda d: d["indicator"].map(LABEL), Window=lambda d: d["year"].map(window))
    g_filt = g[g["indicator"].isin(trend_inds)]
    fig = px.line(g_filt, x="Window", y="moran_I", color="Indicator", markers=True,
                  labels={"moran_I": "Moran's I"})
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Queen contiguity. Largest permutation p-value across all points: {D['glob']['p_value'].max():.4f}.")

    if D["corro"] is not None:
        st.subheader("Spatial correlogram — how far does clustering reach?")
        cr = D["corro"].dropna(subset=["moran_I"]).copy()
        cr["Window"] = cr["year"].map(window)
        cr["Order"] = cr["order"].astype(str)
        cr["Significant"] = cr["p_value"] < 0.05
        csel = st.selectbox("Indicator", list(LABEL), format_func=LABEL.get, key="corro_ind")
        cr_ind = cr[cr["indicator"] == csel]
        cfig = px.line(cr_ind, x="order", y="moran_I", color="Window", markers=True,
                       labels={"order": "Contiguity order (k)", "moran_I": "Moran's I",
                               "Window": "ACS window"},
                       title=f"Moran's I by contiguity order — {LABEL[csel]}")
        cfig.add_hline(y=0, line_color="grey", line_dash="dot")
        cfig.update_layout(height=370, margin=dict(l=0, r=0, t=50, b=0),
                           xaxis=dict(tickmode="linear", tick0=1, dtick=1))
        st.plotly_chart(cfig, use_container_width=True)
        st.caption(
            "Each order k uses only the k-th-order queen neighbours (non-cumulative), so the bands do not overlap. "
            "A rapid decay toward zero indicates clustering is largely a local phenomenon; "
            "a slow decay indicates broad regional gradients that persist beyond immediate neighbours."
        )


# --------------------------------------------------------------- robustness
with tab_rob:
    st.subheader("How much does ACS sampling error change the picture?")
    st.markdown(
        "Each county estimate is redrawn "
        f"{P['stability_draws']} times from its published margin of error and the analysis is repeated. "
        "Stability below uses the unadjusted permutation test (see *Method and caveats*)."
    )
    rwin = st.radio("ACS window", WINDOWS, index=len(WINDOWS) - 1, format_func=window, horizontal=True, key="rob_window")
    stab_w = stab_all[stab_all["year"] == rwin]
    rob_w = rob_all[rob_all["year"] == rwin]

    all_ind_names = list(LABEL)
    sel_inds = st.multiselect(
        "Indicators to show in plots",
        options=all_ind_names,
        default=all_ind_names,
        format_func=LABEL.get,
        key="rob_ind_filter",
    )
    if not sel_inds:
        sel_inds = all_ind_names  # fall back to all if nothing chosen

    mg = (D["moe_glob"][D["moe_glob"]["year"] == rwin]
          .assign(Indicator=lambda d: d["indicator"].map(LABEL)))
    mg_filt = mg[mg["indicator"].isin(sel_inds)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mg_filt["Indicator"], y=mg_filt["moran_I_point"], mode="markers", name="Point estimate",
                             marker=dict(size=11, color="#0f766e"),
                             error_y=dict(type="data", symmetric=False,
                                          array=mg_filt["moran_I_sim_p95"] - mg_filt["moran_I_point"],
                                          arrayminus=mg_filt["moran_I_point"] - mg_filt["moran_I_sim_p05"])))
    fig.update_layout(height=380, yaxis_title="Moran's I", margin=dict(l=0, r=0, t=50, b=0),
                      title="Observed Moran's I and the 5th-95th percentile range under resampling")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Resampled values are noisier than the published ones, so the resampled average sits below the observed value.")

    st.subheader("Stability of nominally significant clusters")
    nominal = stab_w[stab_w["cluster_headline_raw"] != "Not significant"].copy()
    nominal = nominal[nominal["indicator"].isin(sel_inds)]
    nominal["Indicator"] = nominal["indicator"].map(LABEL)
    nominal["After FDR"] = nominal["cluster_headline_fdr"] != "Not significant"
    fig = px.strip(nominal, x="Indicator", y="share_draws_same_raw_class", color="After FDR", hover_name="NAME",
                   color_discrete_map={True: "#b2182b", False: "#9aa5b1"},
                   labels={"share_draws_same_raw_class": "Share of draws keeping the same cluster label"})
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader(f"The clusters that survive FDR correction, and the other two checks ({window(rwin)})")
    show = rob_w.assign(Indicator=rob_w["indicator"].map(LABEL)).rename(columns={
        "NAME": "County", "cluster_headline_fdr": "Cluster", "passes_analytic": "Same under analytic test",
        "share_draws_same_raw_class": "Stability", "robust": "Passes all three"})
    show["Stability"] *= 100
    st.dataframe(show[["Indicator", "County", "Cluster", "Same under analytic test", "Stability", "Passes all three"]],
                 hide_index=True, use_container_width=True,
                 column_config={"Stability": st.column_config.NumberColumn(format="%.0f%%")})


# ------------------------------------------------------------------ models
with tab_model:
    st.subheader("Does a spatial model beat ordinary regression? (poverty rate, latest window)")
    wsel = st.radio("Spatial weights", sorted(D["mcomp"]["weights"].unique(), key=lambda w: (w != "queen", w)), horizontal=True)
    comp = D["mcomp"][D["mcomp"]["weights"] == wsel].drop(columns="weights")
    _COMP_LABELS = {
        "model":              "Model",
        "AIC":                "AIC",
        "logLik":             "Log-likelihood",
        "spatial_param":      "Spatial parameter",
        "spatial_param_name": "Parameter name",
        "resid_moran_I":      "Moran's I (residuals)",
        "resid_moran_p":      "p-value (Moran's I)",
    }
    comp = comp.rename(columns=_COMP_LABELS)
    st.dataframe(comp.round(4), hide_index=True, use_container_width=True)
    st.caption("Predictors are standardised, so coefficients are the change in poverty rate per one standard deviation. "
               "Income is excluded because it is almost a mechanical function of poverty.")

    co = D["mcoef"]
    co = co[(co["model"] == "OLS") | (co["weights"] == wsel)].copy()
    co = co[co["term"] != "(Intercept)"]
    co["Predictor"] = co["term"].map(an.TERM_LABELS).fillna(co["term"])
    co["lo"] = co["Estimate"] - 1.96 * co["Std. Error"]
    co["hi"] = co["Estimate"] + 1.96 * co["Std. Error"]

    all_models = sorted(co["model"].unique().tolist())
    all_predictors = [p for p in ([t for t in an.TERM_LABELS.values() if t != "Intercept"] +
                                   [p for p in co["Predictor"].unique() if p not in an.TERM_LABELS.values()])
                      if p in co["Predictor"].values]

    coef_col1, coef_col2 = st.columns([2, 3])
    with coef_col1:
        sel_models = st.multiselect("Models", all_models, default=all_models, key="coef_models")
        if not sel_models:
            sel_models = all_models
    with coef_col2:
        sel_preds = st.multiselect("Predictors", all_predictors, default=all_predictors, key="coef_preds")
        if not sel_preds:
            sel_preds = all_predictors

    co_filt = co[co["model"].isin(sel_models) & co["Predictor"].isin(sel_preds)]
    order = [p for p in all_predictors if p in sel_preds]
    palette = ["#0f766e", "#b45309", "#6d28d9", "#c2410c", "#1d4ed8", "#7c3aed", "#0369a1", "#15803d"]
    n_models = len(sel_models)
    spread = 0.3
    offsets = {m: (i - (n_models - 1) / 2) * (spread / max(n_models - 1, 1))
               for i, m in enumerate(sel_models)}

    fig = go.Figure()
    for i, mname in enumerate(sel_models):
        m = co_filt[co_filt["model"] == mname]
        color = palette[i % len(palette)]
        ypos = [order.index(t) + offsets[mname] for t in m["Predictor"] if t in order]
        m_ord = m[m["Predictor"].isin(order)]
        fig.add_trace(go.Scatter(
            x=m_ord["Estimate"], y=ypos, mode="markers", name=mname,
            marker=dict(color=color, size=8),
            error_x=dict(type="data", symmetric=False,
                         array=(m_ord["hi"] - m_ord["Estimate"]).tolist(),
                         arrayminus=(m_ord["Estimate"] - m_ord["lo"]).tolist(),
                         color=color),
            hovertext=m_ord["Predictor"].tolist()))
    fig.update_yaxes(tickmode="array", tickvals=list(range(len(order))), ticktext=order, autorange="reversed")
    fig.add_vline(x=0, line_color="grey")
    fig.update_layout(height=max(320, 60 * len(order)), margin=dict(l=0, r=0, t=50, b=0),
                      title="Coefficients with 95% intervals")
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns([2, 3])
    with c1:
        st.subheader("Residual diagnostics")
        dg = D["mdiag"][D["mdiag"]["weights"] == wsel].drop(columns="weights")
        st.dataframe(dg.round(4), hide_index=True, use_container_width=True)
    with c2:
        resid_options = list(D["resid_map"].keys())
        resid_sel = st.selectbox("Residuals — model", resid_options, key="resid_model_sel")
        res = D["resid_map"][resid_sel]
        # Auto-detect the residual column (first non-GEOID/NAME column)
        resid_col = next((c for c in res.columns if c not in ("GEOID", "NAME")), res.columns[-1])
        rfig = px.choropleth_map(res, geojson=D["geo"], locations="GEOID", featureidkey="properties.GEOID",
                                 color=resid_col, color_continuous_scale="RdBu_r", color_continuous_midpoint=0,
                                 hover_name="NAME", map_style="white-bg", center={"lat": 35.3, "lon": -79.4},
                                 zoom=4.6, opacity=0.85, labels={resid_col: "Residual"})
        rfig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=330)
        rfig.update_coloraxes(colorbar=dict(orientation="h", y=-0.05, thickness=10, len=0.7, title=dict(text="")))
        st.plotly_chart(rfig, use_container_width=True)
        st.caption("Large positive residuals may be college counties, where student populations raise measured poverty. "
                   "This is a hypothesis to check, not a result.")

# ------------------------------------------------------------------- about
with tab_about:
    st.subheader("Method")
    st.markdown(
        f"""
**Data.** ACS 5-year county estimates for North Carolina (windows ending {', '.join(map(str, WINDOWS))}), pulled with
`tidycensus` with margins of error. Ratio indicators carry propagated margins of error.

**Spatial structure.** Global Moran's I and local Moran's I (LISA) with queen-contiguity weights and
{P['n_permutations']:,} conditional permutations. Local p-values are adjusted for 100 simultaneous tests with the
Benjamini-Hochberg procedure (FDR). Neighbour definitions (queen, 5 and 8 nearest) are compared.

**Sampling error.** Each estimate is redrawn from Normal(estimate, (MOE / 1.645)^2) because ACS margins of error are
90% intervals, {P['stability_draws']} times, and local Moran's I is recomputed with {P['stability_permutations']} permutations.

**Models.** OLS for the poverty rate, Lagrange multiplier tests on the residuals, then spatial lag, spatial error and
spatial Durbin models.

**Three checks for a robust cluster.** (1) significant after FDR correction, (2) the same label under the analytic
(normal-theory) test, and (3) stable in at least 90% of resampled draws.

**Estimate reliability (CV tiers).** Each ACS estimate carries a margin of error (MOE, 90% interval). The
coefficient of variation CV = (MOE / 1.645) / |estimate| summarises precision. CV < 12 %: Reliable;
12–40 %: Use with caution; > 40 %: Unreliable (U.S. Census Bureau convention). Counties with unreliable
estimates are assigned the "Unreliable estimate" evidence grade regardless of significance.

**Evidence grade.** Each county × indicator × window is assigned one of five ordered grades synthesising
estimate reliability, statistical significance, and MOE stability:
*Robust* (FDR-significant + same analytic label + ≥ 90 % stable) → *FDR-significant* → *Nominal only*
(unadjusted p < 0.05 but not FDR) → *No cluster* → *Unreliable estimate* (CV > 40 %).

**Spatial correlogram.** Moran's I is computed separately at each queen-contiguity order k = 1 … 5 using
non-overlapping k-th-order neighbour bands (via `nblag()`). The decay profile reveals how far spatial
dependence extends beyond immediate neighbours.

**Bivariate LISA.** For three indicator pairs (poverty × unemployment, income × poverty, education × poverty),
each county's focal-indicator value is compared against its neighbours' lagged-indicator value using
`localmoran_bv()` (spdep ≥ 1.2-1). p-values are FDR-adjusted (BH). A High-High county has a high focal
value surrounded by counties with high lagged values.
"""
    )
    n_fdr, n_method = len(rob), int((~rob["passes_analytic"]).sum())
    st.subheader("Caveats")
    st.markdown(
        f"""
- Stability uses the unadjusted permutation test, because FDR correction at n = 100 needs p-values that a 999-permutation
  run inside a Monte Carlo loop cannot resolve. A cluster that fails even this test is fragile; one that passes is not proven robust.
- Resampling treats county errors as independent and Normal, ignoring correlation between neighbours and the skew of ratio estimates.
- {n_method} of the {n_fdr} FDR-significant clusters are significant under the permutation test but not the analytic test, so they depend on the method.
- Results are descriptive and ecological (county aggregates). They are not causal estimates.
- ACS windows are non-overlapping five-year periods, so each is a pooled-period estimate.
- Border counties (those sharing a boundary with Virginia, South Carolina, Tennessee, or Georgia) have
  truncated neighbour lists because the analysis covers only North Carolina. Their spatial lags underweight
  out-of-state neighbours. This affects higher-order correlogram bands most strongly.
"""
    )
    st.subheader("Downloads")
    d1, d2, d3 = st.columns(3)
    d1.download_button("County clusters (CSV)", (an.DATA_DIR / "local_clusters.csv").read_bytes(), "nc_local_clusters.csv")
    d2.download_button("Indicators with MOE (CSV)", (an.DATA_DIR / "indicators.csv").read_bytes(), "nc_indicators.csv")
    d3.download_button("Stability by county (CSV)", (an.DATA_DIR / "stability_county.csv").read_bytes(), "nc_stability.csv")
    _dl_new = [
        ("Evidence grades (CSV)", "evidence_grades.csv", "nc_evidence_grades.csv"),
        ("Correlogram (CSV)",     "correlogram.csv",     "nc_correlogram.csv"),
        ("Bivariate LISA (CSV)",  "bivariate_lisa.csv",  "nc_bivariate_lisa.csv"),
    ]
    _dl_avail = [(lbl, src, dst) for lbl, src, dst in _dl_new if (an.DATA_DIR / src).exists()]
    if _dl_avail:
        d4, d5, d6 = st.columns(3)
        for col, (lbl, src, dst) in zip([d4, d5, d6], _dl_avail):
            col.download_button(lbl, (an.DATA_DIR / src).read_bytes(), dst)
    with st.expander("Build metadata"):
        st.json(META)
