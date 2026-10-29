"""Integrity tests for the result files in app/data/ and a smoke test of the Streamlit app.

These guard the contract between the R pipeline (which writes the files) and the app (which reads them),
and cross-check the R and Python implementations of Moran's I.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import analysis as an  # noqa: E402

CLUSTERS = set(an.CLUSTER_ORDER)


@pytest.fixture(scope="module")
def data():
    names = {
        "ind": "indicators.csv", "local": "local_clusters.csv", "glob": "global_moran.csv",
        "stab": "stability_county.csv", "nb": "neighbors.csv", "sens": "weights_sensitivity.csv",
        "mcomp": "model_comparison.csv", "mcoef": "model_coefficients.csv", "mres": "model_ols_residuals.csv",
    }
    d = {k: an.read_csv(f) for k, f in names.items()}
    d["geo"] = an.read_geojson()
    d["meta"] = an.read_meta()
    return d


def test_geometry_has_100_unique_nc_counties(data):
    feats = data["geo"]["features"]
    ids = [f["properties"]["GEOID"] for f in feats]
    assert len(ids) == len(set(ids)) == 100
    assert all(i.startswith("37") and len(i) == 5 for i in ids)
    lons, lats = [], []
    for f in feats:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for x, y in poly[0]:
                lons.append(x); lats.append(y)
    assert -85 < min(lons) and max(lons) < -75 and 33 < min(lats) and max(lats) < 37   # inside North Carolina


def test_every_table_covers_the_same_counties(data):
    geo_ids = {f["properties"]["GEOID"] for f in data["geo"]["features"]}
    for key in ["ind", "local", "stab", "mres"]:
        assert set(data[key]["GEOID"]) == geo_ids, key
    assert set(data["nb"]["GEOID"]) == geo_ids and set(data["nb"]["neighbor"]) <= geo_ids


def test_neighbor_list_is_symmetric_and_has_no_self_links(data):
    nb = data["nb"]
    pairs = set(zip(nb["GEOID"], nb["neighbor"]))
    assert all((b, a) in pairs for a, b in pairs)
    assert all(a != b for a, b in pairs)


def test_indicator_values_are_plausible(data):
    ind = data["ind"]
    for rate in ["poverty_rate", "unemp_rate", "ba_plus_rate"]:
        assert ind[rate].between(0, 1).all(), rate
        assert (ind[f"{rate}_moe"] >= 0).all()
    assert ind["med_hh_income"].between(10_000, 250_000).all()
    assert ind["med_age"].between(20, 70).all()
    assert set(ind["year"]) == set(data["meta"]["acs_windows"])


def test_cluster_tables_are_internally_consistent(data):
    loc = data["local"]
    assert set(loc["cluster_raw"]) <= CLUSTERS and set(loc["cluster_fdr"]) <= CLUSTERS
    assert (loc["p_fdr"] >= loc["p_value"] - 1e-12).all()                 # FDR p never below raw p
    flagged = loc["cluster_fdr"] != "Not significant"
    assert (loc.loc[flagged, "cluster_raw"] != "Not significant").all()   # FDR-significant implies nominally significant
    assert (loc.loc[flagged, "p_fdr"] < 0.05).all()
    unflagged = loc["cluster_raw"] == "Not significant"
    assert (loc.loc[unflagged, "p_value"] >= 0.05).all()
    assert len(loc) == 100 * len(set(loc["year"])) * loc["indicator"].nunique()


def test_stability_shares_are_probabilities(data):
    s = data["stab"]
    for c in ["share_draws_same_raw_class", "share_draws_raw_significant"]:
        assert s[c].between(0, 1).all()
    # a county that keeps its nominal cluster type in a draw is also significant in that draw
    assert (s["share_draws_raw_significant"] + 1e-12 >= s["share_draws_same_raw_class"]).where(
        s["cluster_headline_raw"] != "Not significant", True).all()


def test_python_moran_matches_r_for_every_indicator_and_window(data):
    """Cross-language check: Moran's I recomputed in pandas from the neighbour list equals the R result."""
    ind, nb, glob = data["ind"], data["nb"], data["glob"]
    for _, row in glob.iterrows():
        vals = ind[ind["year"] == row["year"]].set_index("GEOID")[row["indicator"]]
        assert an.morans_i(vals, nb) == pytest.approx(row["moran_I"], abs=1e-9), (row["indicator"], row["year"])


def test_model_tables(data):
    comp = data["mcomp"]
    assert {"OLS", "SAR_lag", "SEM_error", "SDM_durbin"} <= set(comp["model"])
    assert comp["AIC"].notna().all()
    assert data["mcoef"]["term"].notna().all()


def test_app_runs_without_errors_and_across_selections():
    """Smoke test: the Streamlit script executes, and keeps working when the sidebar selections change."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 6
    assert len(at.metric) == 4

    for indicator in ["unemp_rate", "med_hh_income"]:
        at.sidebar.selectbox[0].set_value(indicator).run()
        assert not at.exception, [e.value for e in at.exception]
        for view in ["Clusters (FDR-adjusted)", "Clusters (unadjusted)", "Values"]:
            at.sidebar.radio[1].set_value(view).run()
            assert not at.exception, (indicator, view, [e.value for e in at.exception])
