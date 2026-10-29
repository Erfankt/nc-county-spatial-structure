"""NC County Spatial Structure explorer.

Reads the result files written by the R pipeline (app/data/) and lets you explore where North Carolina
counties cluster, how that changed between ACS windows, and how much of it survives ACS sampling error.
Run locally:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

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
view = st.sidebar.radio("Map shows", ["Values", "Clusters (FDR-adjusted)", "Clusters (unadjusted)"])
st.sidebar.markdown("---")
st.sidebar.caption(
    f"Built {META['built_at']}. {P['n_permutations']:,} permutations, seed {P['seed']}. "
    "Data: U.S. Census Bureau, American Community Survey."
)

# ------------------------------------------------------------- tabs
st.title("Where do North Carolina counties cluster, and how much of it is real?")
st.caption(
    "Spatial autocorrelation of county socioeconomic indicators, with multiple-testing correction and "
    "a check against ACS sampling error."
)
tab_over, tab_map, tab_time, tab_rob, tab_model, tab_about = st.tabs(
    ["Overview", "Map explorer", "Over time", "Robustness", "Models", "Method and caveats"]
)

local = D["local"]
stab = D["stab"]
rob = an.robust_clusters(stab)

# ---------------------------------------------------------------- overview
with tab_over:
    g = D["glob"]
    g_latest = g[g["year"] == LATEST]
    fdr_latest = local[(local["year"] == LATEST) & (local["cluster_fdr"] != "Not significant")]
    raw_latest = local[(local["year"] == LATEST) & (local["cluster_raw"] != "Not significant")]
    n_tests = len(ind_df)  # indicators analysed

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Global Moran's I range", f"{g_latest['moran_I'].min():.2f} to {g_latest['moran_I'].max():.2f}",
              help=f"Across {n_tests} indicators, ACS {LATEST}. All significant.")
    c2.metric("Nominal local clusters", len(raw_latest), help="Unadjusted p < 0.05, all indicators, latest window.")
    c3.metric("After FDR correction", len(fdr_latest), help="Benjamini-Hochberg across 100 counties per indicator.")
    c4.metric("Pass all three checks", int(rob["robust"].sum()),
              help="FDR-significant, same label under the analytic test, and stable under margin-of-error resampling.")

    st.subheader("What the results say")
    diag = D["mdiag"]
    resid_q = diag[(diag["weights"] == "queen") & (diag["test"].str.contains("Moran"))].iloc[0]
    comp = D["mcomp"]
    best = comp[comp["weights"] == "queen"].sort_values("AIC").iloc[0]
    ols_aic = comp[(comp["weights"] == "queen") & (comp["model"] == "OLS")]["AIC"].iloc[0]
    first, last = WINDOWS[0], WINDOWS[-1]
    pv = g[g["indicator"] == "poverty_rate"].set_index("year")["moran_I"]
    un = g[g["indicator"] == "unemp_rate"].set_index("year")["moran_I"]
    st.markdown(
        f"- **Broad regional gradients.** Every indicator is significantly clustered in every window "
        f"(Moran's I between {g['moran_I'].min():.2f} and {g['moran_I'].max():.2f}). Neighbouring counties resemble each other.\n"
        f"- **Few sharp hot spots.** After correcting for 100 simultaneous tests, only {len(fdr_latest)} county-level "
        f"clusters remain in {LATEST} ({len(raw_latest)} before correction). Only {int(rob['robust'].sum())} pass all three checks.\n"
        f"- **Clustering is changing.** Poverty's Moran's I moved from {pv[first]:.2f} to {pv[last]:.2f} and unemployment's "
        f"from {un[first]:.2f} to {un[last]:.2f} between the {an.WINDOW_LABELS.get(first, first)} and "
        f"{an.WINDOW_LABELS.get(last, last)} windows.\n"
        f"- **Spatial models add little for poverty.** Residual Moran's I after OLS is {resid_q['statistic']:.3f} "
        f"(p = {resid_q['p_value']:.2f}). " + (
            f"OLS has the lowest AIC ({ols_aic:.1f}); the spatial models do not improve on it, so most of the clustering "
            "reflects where county characteristics are."
            if best["model"] == "OLS" else
            f"The best model by AIC is {best['model']} ({best['AIC']:.1f} vs {ols_aic:.1f} for OLS).")
    )
    st.subheader("Clusters that pass all three checks")
    rtab = rob[rob["robust"]].assign(Indicator=lambda d: d["indicator"].map(LABEL))
    if len(rtab):
        rt = rtab[["Indicator", "NAME", "cluster_headline_fdr", "share_draws_same_raw_class"]].rename(
            columns={"NAME": "County", "cluster_headline_fdr": "Cluster",
                     "share_draws_same_raw_class": "Resampled draws keeping the label"})
        rt["Resampled draws keeping the label"] *= 100
        st.dataframe(rt, hide_index=True, use_container_width=True, column_config={
            "Resampled draws keeping the label": st.column_config.NumberColumn(format="%.0f%%")})
    else:
        st.info("No cluster passes all three checks.")
    st.caption("These are descriptive spatial patterns in county-level data, not causal estimates.")

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
    if view == "Values":
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
        sc = sc.rename(columns={cl_col: "Cluster"}) if view != "Values" else sc.assign(Cluster="Not significant")
        sfig = px.scatter(sc, x="z", y="lag_z", color="Cluster", hover_name="NAME",
                          color_discrete_map=an.CLUSTER_COLORS, category_orders={"Cluster": an.CLUSTER_ORDER},
                          labels={"z": "Standardised value", "lag_z": "Neighbour average"})
        sfig.add_hline(y=0, line_color="grey"); sfig.add_vline(x=0, line_color="grey")
        sfig.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0), showlegend=(view != "Values"))
        st.plotly_chart(sfig, use_container_width=True)
        gi = an.morans_i(vals, D["nb"])
        st.caption(f"Global Moran's I = {gi:.3f}, recomputed in the app from the neighbour list.")
        sig = sub[sub[cl_col] != "Not significant"] if view != "Values" else sub.iloc[0:0]
        if view != "Values":
            st.markdown(f"**{len(sig)} counties** flagged")
            st.dataframe(sig[["NAME", cl_col, "Estimate", "FDR p"]].rename(columns={"NAME": "County", cl_col: "Cluster"}),
                         hide_index=True, use_container_width=True, height=200)
    with st.expander("Counties with the least precise estimates"):
        sub["Relative MOE"] = (sub["moe"] / sub["value"].abs()).round(3)
        st.dataframe(sub.sort_values("Relative MOE", ascending=False).head(10)[
            ["NAME", "Estimate", "Margin of error (90%)", "Relative MOE"]].rename(columns={"NAME": "County"}),
            hide_index=True, use_container_width=True)

# --------------------------------------------------------------- over time
with tab_time:
    st.subheader("Global Moran's I by ACS window")
    g = D["glob"].assign(Indicator=lambda d: d["indicator"].map(LABEL), Window=lambda d: d["year"].map(window))
    fig = px.line(g, x="Window", y="moran_I", color="Indicator", markers=True,
                  labels={"moran_I": "Moran's I"})
    fig.update_layout(height=400, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Queen contiguity. Largest permutation p-value across all points: {D['glob']['p_value'].max():.4f}.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"Sensitivity to the neighbour definition: {LABEL[indicator]}")
        s = D["sens"][D["sens"]["indicator"] == indicator]
        fig = px.bar(s, x="weights", y="moran_I", labels={"weights": "Weights", "moran_I": "Moran's I"})
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"{an.WINDOW_LABELS.get(LATEST)} window. Queen = shared border; kNN = k nearest centroids.")
    with c2:
        st.subheader(f"Clusters per window: {LABEL[indicator]}")
        cc = local[local["indicator"] == indicator].copy()
        cc["Window"] = cc["year"].map(window)
        tab = pd.DataFrame({
            "Nominal (unadjusted)": cc[cc["cluster_raw"] != "Not significant"].groupby("Window").size(),
            "After FDR": cc[cc["cluster_fdr"] != "Not significant"].groupby("Window").size(),
        }).reindex([window(y) for y in WINDOWS]).fillna(0).astype(int)
        st.dataframe(tab, use_container_width=True)
        pr = D["persist"][D["persist"]["indicator"] == indicator]
        st.caption("Counties significant after FDR in more than one window: " +
                   (", ".join(pr[pr["n_windows"] > 1]["NAME"].tolist()) or "none"))

# --------------------------------------------------------------- robustness
with tab_rob:
    st.subheader("How much does ACS sampling error change the picture?")
    st.markdown(
        "Each county estimate is redrawn "
        f"{P['stability_draws']} times from its published margin of error and the analysis is repeated. "
        "Stability below uses the unadjusted permutation test (see *Method and caveats*)."
    )
    mg = D["moe_glob"].assign(Indicator=lambda d: d["indicator"].map(LABEL))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mg["Indicator"], y=mg["moran_I_point"], mode="markers", name="Point estimate",
                             marker=dict(size=11, color="#0f766e"),
                             error_y=dict(type="data", symmetric=False,
                                          array=mg["moran_I_sim_p95"] - mg["moran_I_point"],
                                          arrayminus=mg["moran_I_point"] - mg["moran_I_sim_p05"])))
    fig.update_layout(height=380, yaxis_title="Moran's I", margin=dict(l=0, r=0, t=50, b=0),
                      title="Observed Moran's I and the 5th-95th percentile range under resampling")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Resampled values are noisier than the published ones, so the resampled average sits below the observed value.")

    st.subheader("Stability of nominally significant clusters")
    nominal = stab[stab["cluster_headline_raw"] != "Not significant"].copy()
    nominal["Indicator"] = nominal["indicator"].map(LABEL)
    nominal["After FDR"] = nominal["cluster_headline_fdr"] != "Not significant"
    fig = px.strip(nominal, x="Indicator", y="share_draws_same_raw_class", color="After FDR", hover_name="NAME",
                   color_discrete_map={True: "#b2182b", False: "#9aa5b1"},
                   labels={"share_draws_same_raw_class": "Share of draws keeping the same cluster label"})
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("The clusters that survive FDR correction, and the other two checks")
    show = rob.assign(Indicator=rob["indicator"].map(LABEL)).rename(columns={
        "NAME": "County", "cluster_headline_fdr": "Cluster", "passes_analytic": "Same under analytic test",
        "share_draws_same_raw_class": "Stability", "robust": "Passes all three"})
    show["Stability"] *= 100
    st.dataframe(show[["Indicator", "County", "Cluster", "Same under analytic test", "Stability", "Passes all three"]],
                 hide_index=True, use_container_width=True,
                 column_config={"Stability": st.column_config.NumberColumn(format="%.0f%%")})

    st.subheader("How noisy are the ACS estimates?")
    ms = D["moe_sum"].assign(Indicator=lambda d: d["name"].map(LABEL))
    st.dataframe(ms[["Indicator", "median_rel_moe_pct", "max_rel_moe_pct"]].rename(columns={
        "median_rel_moe_pct": "Median margin of error (% of estimate)", "max_rel_moe_pct": "Largest (% of estimate)"}).round(1),
        hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ models
with tab_model:
    st.subheader("Does a spatial model beat ordinary regression? (poverty rate, latest window)")
    wsel = st.radio("Spatial weights", sorted(D["mcomp"]["weights"].unique(), key=lambda w: (w != "queen", w)), horizontal=True)
    comp = D["mcomp"][D["mcomp"]["weights"] == wsel].drop(columns="weights")
    st.dataframe(comp.round(4), hide_index=True, use_container_width=True)
    st.caption("Predictors are standardised, so coefficients are the change in poverty rate per one standard deviation. "
               "Income is excluded because it is almost a mechanical function of poverty.")

    co = D["mcoef"]
    co = co[(co["model"] == "OLS") | (co["weights"] == wsel)].copy()
    co = co[co["term"] != "(Intercept)"]
    co["Predictor"] = co["term"].map(an.TERM_LABELS)
    co["lo"] = co["Estimate"] - 1.96 * co["Std. Error"]
    co["hi"] = co["Estimate"] + 1.96 * co["Std. Error"]
    co = co[co["model"].isin(["OLS", "SAR_lag", "SEM_error"])]
    order = [t for t in an.TERM_LABELS.values() if t != "Intercept"]
    offsets = {"OLS": -0.2, "SAR_lag": 0.0, "SEM_error": 0.2}
    fig = go.Figure()
    for mname, color in zip(["OLS", "SAR_lag", "SEM_error"], ["#0f766e", "#b45309", "#6d28d9"]):
        m = co[co["model"] == mname]
        ypos = [order.index(t) + offsets[mname] for t in m["Predictor"]]
        fig.add_trace(go.Scatter(x=m["Estimate"], y=ypos, mode="markers", name=mname, marker=dict(color=color, size=8),
                                 error_x=dict(type="data", symmetric=False, array=m["hi"] - m["Estimate"],
                                              arrayminus=m["Estimate"] - m["lo"], color=color),
                                 hovertext=m["Predictor"]))
    fig.update_yaxes(tickmode="array", tickvals=list(range(len(order))), ticktext=order, autorange="reversed")
    fig.add_vline(x=0, line_color="grey")
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=50, b=0), title="Coefficients with 95% intervals")
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns([2, 3])
    with c1:
        st.subheader("Residual diagnostics")
        dg = D["mdiag"][D["mdiag"]["weights"] == wsel].drop(columns="weights")
        st.dataframe(dg.round(4), hide_index=True, use_container_width=True)
    with c2:
        st.subheader("OLS residuals")
        res = D["mres"]
        rfig = px.choropleth_map(res, geojson=D["geo"], locations="GEOID", featureidkey="properties.GEOID",
                                 color="ols_resid", color_continuous_scale="RdBu_r", color_continuous_midpoint=0,
                                 hover_name="NAME", map_style="white-bg", center={"lat": 35.3, "lon": -79.4},
                                 zoom=4.6, opacity=0.85, labels={"ols_resid": "Residual"})
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
"""
    )
    st.subheader("Downloads")
    d1, d2, d3 = st.columns(3)
    d1.download_button("County clusters (CSV)", (an.DATA_DIR / "local_clusters.csv").read_bytes(), "nc_local_clusters.csv")
    d2.download_button("Indicators with MOE (CSV)", (an.DATA_DIR / "indicators.csv").read_bytes(), "nc_indicators.csv")
    d3.download_button("Stability by county (CSV)", (an.DATA_DIR / "stability_county.csv").read_bytes(), "nc_stability.csv")
    with st.expander("Build metadata"):
        st.json(META)
