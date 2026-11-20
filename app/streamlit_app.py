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
import plotly.io as pio
import streamlit as st

import analysis as an

st.set_page_config(page_title="NC County Spatial Structure", page_icon="\U0001f9ed", layout="wide")


# -------------------------------------------------------------- theme ("Field Atlas")
# A distinct editorial-cartography look: parchment background, deep pine headings,
# a clay/terracotta accent, serif display type over a plain sans body. Purely
# cosmetic -- no functional change to any widget, chart, or data flow below.
_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=Inter:wght@400;500;600;700&display=swap');

:root {
  --fa-ink: #2b2420;
  --fa-paper: #faf6f0;
  --fa-paper-deep: #f0e8d9;
  --fa-pine: #16423c;
  --fa-pine-light: #2f6659;
  --fa-clay: #c2410c;
  --fa-clay-light: #e08a52;
  --fa-rule: #d8cdb8;
  --fa-sidebar-text: #f3ede0;
}

html, body, .stApp { background-color: var(--fa-paper) !important; }
.stApp, .stApp p, .stApp li, .stApp span, .stApp div { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }

/* Material icon glyphs (expander chevrons, select/multiselect arrows, etc.) must keep
   their own icon font -- the broad font-family rule above otherwise turns the glyph
   ligature into literal text like "arrow_down" stacked on top of the label. */
[data-testid="stIconMaterial"],
[class*="material-symbols"],
[class*="MaterialSymbols"] {
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
  font-weight: normal !important;
}

h1, h2, h3 { font-family: 'Source Serif 4', Georgia, serif !important; color: var(--fa-pine) !important; letter-spacing: -0.01em; }
[data-testid="stMarkdownContainer"] h3 { border-left: 4px solid var(--fa-clay); padding-left: 0.6rem; margin-top: 0.3rem; }

.fa-kicker, .fa-sidebar-kicker {
  font-family: 'Inter', sans-serif; font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--fa-clay); margin-bottom: 0.15rem;
}
.fa-sidebar-kicker { color: var(--fa-clay-light); font-size: 0.68rem; }
.fa-hero h1 { margin: 0 0 0.3rem 0 !important; font-size: 2.05rem !important; line-height: 1.18; }
.fa-hero p { color: #6b5f4f; font-size: 0.82rem; max-width: 100%; white-space: nowrap; margin: 0 0 0.6rem 0; }
.fa-hero-rule { height: 3px; width: 64px; background: var(--fa-clay); margin: 0.35rem 0 1.2rem 0; border-radius: 2px; }
.fa-map-title { font-family: 'Source Serif 4', Georgia, serif; color: var(--fa-pine); font-weight: 600; font-size: 1.05rem; margin: 0 0 0.5rem 0; }
.fa-controls-kicker { font-family: 'Inter', sans-serif; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--fa-clay); margin: 0 0 0.3rem 0; }

/* ---- Sidebar: dark pine panel, cream text for labels/headings, light cards for inputs ---- */
[data-testid="stSidebar"] { background-color: var(--fa-pine) !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: var(--fa-sidebar-text) !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: var(--fa-sidebar-text) !important; }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] label { color: var(--fa-sidebar-text) !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #cddbd3 !important; }
[data-testid="stSidebar"] [data-testid="stRadio"] label,
[data-testid="stSidebar"] [data-testid="stCheckbox"] label { color: var(--fa-sidebar-text) !important; }
[data-testid="stSidebar"] hr { border-color: rgba(243,237,224,0.25) !important; }

/* ---- Tabs ---- */
[data-baseweb="tab-list"] { gap: 1.6rem; border-bottom: 1px solid var(--fa-rule); }
[data-baseweb="tab"] { font-family: 'Source Serif 4', Georgia, serif; font-size: 1.02rem; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--fa-clay) !important; font-weight: 600; }

/* ---- Buttons ---- */
.stButton > button, .stDownloadButton > button {
  background-color: var(--fa-clay); color: #fff8f0; border: 1px solid var(--fa-clay);
  border-radius: 6px; font-weight: 600;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background-color: var(--fa-clay-light); border-color: var(--fa-clay-light); color: #fff;
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
  background-color: #c9bfa8; border-color: #c9bfa8; color: #fff; opacity: 0.75;
}

/* ---- Expander: a light card regardless of what it sits on ---- */
[data-testid="stExpander"] { border: 1px solid var(--fa-rule) !important; border-radius: 10px !important; overflow: hidden; }

/* ---- Dataframes / tables ---- */
[data-testid="stDataFrame"] { border: 1px solid var(--fa-rule); border-radius: 8px; overflow: hidden; }

/* ---- Captions (main area) ---- */
[data-testid="stCaptionContainer"] { color: #6b5f4f !important; }

/* ---- Code block (pipeline log) ---- */
.stCodeBlock, pre { border-radius: 8px !important; }
</style>
"""
st.markdown(_THEME_CSS, unsafe_allow_html=True)

# Matching Plotly template: same palette/typography, applied to every chart in the app.
# Explicit color maps elsewhere (cluster/grade/CV-tier colors, the coefficient palette)
# are untouched -- this only sets fonts, backgrounds, gridlines, and the default
# categorical color cycle for charts that don't specify their own colors.
_FA_COLORWAY = [
    "#16423c", "#c2410c", "#5b4b8a", "#b08900", "#2f6659", "#8c3b3b",
    "#3d6e8c", "#7a7a52", "#9a4f96", "#4f7942", "#a65b3a", "#4a5759",
]
pio.templates["fieldatlas"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Inter, -apple-system, sans-serif", color="#2b2420", size=13),
        title=dict(font=dict(family="Source Serif 4, Georgia, serif", color="#16423c", size=16)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=_FA_COLORWAY,
        xaxis=dict(gridcolor="#e7ddc9", linecolor="#d8cdb8", zerolinecolor="#d8cdb8"),
        yaxis=dict(gridcolor="#e7ddc9", linecolor="#d8cdb8", zerolinecolor="#d8cdb8"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#faf6f0", bordercolor="#c2410c",
                        font=dict(color="#2b2420", family="Inter, sans-serif")),
    )
)
pio.templates.default = "fieldatlas"


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


# ------------------------------------------------- refresh data (local only)
def _find_rscript() -> str | None:
    """Locate Rscript: PATH first, then common Windows install folders."""
    exe = shutil.which("Rscript")
    if exe:
        return exe
    candidates = sorted(glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe")) + \
        sorted(glob.glob(r"C:\Program Files (x86)\R\R-*\bin\Rscript.exe"))
    return candidates[-1] if candidates else None


_view_opts = (["Evidence grade"] if D["evidence"] is not None else []) + \
    ["Values", "Clusters (FDR-adjusted)", "Clusters (unadjusted)"]


# ------------------------------------------------------------- tabs
st.markdown(
    """
    <div class="fa-hero">
      <h1>Where do North Carolina counties cluster?</h1>
      <p>Spatial autocorrelation of county socioeconomic indicators, with multiple-testing correction.</p>
      <div class="fa-hero-rule"></div>
    </div>
    """,
    unsafe_allow_html=True,
)
(tab_map,) = st.tabs(["Map explorer"])

local = D["local"]
stab_all = D["stab"]
rob_all = an.robust_clusters(stab_all)
stab = stab_all[stab_all["year"] == LATEST]   # headline numbers use the latest window
rob = rob_all[rob_all["year"] == LATEST]

# ------------------------------------------------------------ map explorer
with tab_map:
    st.markdown('<div class="fa-controls-kicker">Map controls</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        indicator = st.selectbox("Indicator", list(LABEL), format_func=LABEL.get)
    with c2:
        year = st.radio("ACS window", WINDOWS, index=len(WINDOWS) - 1, format_func=window, horizontal=True)
    with c3:
        view = st.radio(
            "Map shows", _view_opts, horizontal=True,
            help=(
                "**Evidence grade** — one trust label per county, combining FDR significance, "
                "agreement between the permutation and analytic tests, and resampling stability "
                "(*Robust* down to *Unreliable estimate*).\n\n"
                "**Values** — the raw indicator value itself, shaded continuously. No cluster "
                "testing involved.\n\n"
                "**Clusters (FDR-adjusted)** — hotspot/coldspot/outlier labels after correcting "
                "for testing all 100 counties at once. The recommended cluster view.\n\n"
                "**Clusters (unadjusted)** — the same cluster test at a flat 5% cutoff, with no "
                "correction — includes false alarms that FDR adjustment would remove."
            ),
        )
    st.caption(
        f"Built {META['built_at']}. {P['n_permutations']:,} permutations, seed {P['seed']}. "
        "Data: U.S. Census Bureau, American Community Survey."
    )
    # The pipeline runner (and the Census API key field it needs) only ever renders
    # when an R installation is actually found on this machine -- i.e. the author's
    # own computer. A Streamlit Community Cloud deployment has no R runtime, so
    # _find_rscript() always returns None there, and visitors see a plain note
    # instead: no button, no API key field, nothing to run.
    _auto_rscript = _find_rscript()
    if _auto_rscript:
        with st.expander("Refresh Census data (author only — runs locally)"):
            st.caption(
                "Re-pulls every ACS variable from the Census API and rebuilds all files in "
                "app/data/. This only works because R is installed on this machine; it never "
                "appears for visitors to the deployed site."
            )
            _repo_root = an.DATA_DIR.parent.parent  # app/data -> app -> repo root
            api_key = st.text_input(
                "Census API key", type="password",
                value=os.environ.get("CENSUS_API_KEY", ""),
                help="Free key: https://api.census.gov/data/key_signup.html. "
                     "Used only for this run, never written to disk or logged.",
                key="census_api_key_input",
            )
            confirm = st.checkbox(
                "I understand this calls the Census API and can take 10–30 minutes "
                "(153 indicator pairs × 3 ACS windows for bivariate LISA alone)"
            )
            if st.button("Run pipeline now", disabled=not (api_key and confirm)):
                env = os.environ.copy()
                env["CENSUS_API_KEY"] = api_key
                log_lines: list[str] = []
                log_box = st.empty()
                log_box.code("Starting pipeline/run_all.R ...")
                try:
                    proc = subprocess.Popen(
                        [_auto_rscript, "pipeline/run_all.R"],
                        cwd=str(_repo_root), env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1,
                    )
                    for line in proc.stdout:
                        log_lines.append(line.rstrip("\n"))
                        log_box.code("\n".join(log_lines[-200:]) or "(no output yet)")
                    proc.wait()
                except FileNotFoundError:
                    st.error(f"Couldn't run '{_auto_rscript}'.")
                else:
                    if proc.returncode == 0:
                        st.success("Pipeline finished. Reloading data…")
                        load_all.clear()
                        st.rerun()
                    else:
                        st.error(f"Pipeline exited with code {proc.returncode}. See the log above.")
    else:
        st.caption(f"Data last refreshed {META['built_at']}.")
    st.divider()

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
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=440, legend=dict(orientation="h", y=-0.02))
    st.markdown(f'<div class="fa-map-title">{LABEL[indicator]}, {window(year)}</div>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True)

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

