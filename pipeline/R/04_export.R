# 04_export.R -- package the results as the small, public files the web app reads.
# Output: app/data/*  (committed to git; everything else under data/ and outputs/ is regenerated)
#
# Run after 01-03:  Rscript pipeline/R/04_export.R   (or Rscript pipeline/run_all.R)

source("pipeline/R/00_config.R")
source("pipeline/R/helpers.R")
suppressPackageStartupMessages(library(jsonlite))

dir.create("app/data", recursive = TRUE, showWarnings = FALSE)

ind  <- readRDS("data/derived/nc_county_indicators.rds")
geom <- readRDS("data/derived/nc_county_geometry.rds") %>% arrange(GEOID)
tab  <- function(f) read_csv(file.path("outputs/tables", f), show_col_types = FALSE)

# ---- County geometry: WGS84, simplified (~250 m) so the app map stays light ----------
geom_web <- geom %>%
  st_simplify(preserveTopology = TRUE, dTolerance = 250) %>%
  st_transform(4326) %>%
  select(GEOID, NAME)
geojson_path <- "app/data/counties.geojson"
if (file.exists(geojson_path)) file.remove(geojson_path)
st_write(geom_web, geojson_path, driver = "GeoJSON", quiet = TRUE,
         layer_options = "COORDINATE_PRECISION=4")

# ---- Queen-contiguity neighbour list (lets the app rebuild Moran scatterplots) ----------
nb <- poly2nb(geom, queen = TRUE)
neighbors <- tibble(
  GEOID    = rep(geom$GEOID, times = card(nb)),
  neighbor = geom$GEOID[unlist(nb)]
)
write_csv(neighbors, "app/data/neighbors.csv")

# ---- Indicator values with margins of error ---------------------------------------------
write_csv(ind, "app/data/indicators.csv")

# ---- Spatial-structure results ----------------------------------------------------------
write_csv(tab("global_moran_by_year.csv"),            "app/data/global_moran.csv")
write_csv(tab("global_moran_weights_sensitivity.csv"), "app/data/weights_sensitivity.csv")
write_csv(tab("local_moran_clusters_all_years.csv") %>%
            select(GEOID, NAME, year, indicator, value, local_I, p_value, p_fdr,
                   quadrant, cluster_raw, cluster_fdr),
          "app/data/local_clusters.csv")
write_csv(tab("cluster_persistence.csv"),             "app/data/cluster_persistence.csv")

# ---- Margin-of-error robustness ---------------------------------------------------------
write_csv(tab("moe_cluster_stability_county.csv"),    "app/data/stability_county.csv")
write_csv(tab("moe_global_moran_uncertainty.csv"),    "app/data/moe_global_moran.csv")
# How noisy are the latest-window estimates? (margin of error as a % of the estimate)
latest <- ind[ind$year == max(YEARS), ]
moe_summary <- INDICATORS %>%
  mutate(
    median_rel_moe_pct = map_dbl(name, ~ 100 * median(latest[[paste0(.x, "_moe")]] / abs(latest[[.x]]), na.rm = TRUE)),
    max_rel_moe_pct    = map_dbl(name, ~ 100 * max(latest[[paste0(.x, "_moe")]] / abs(latest[[.x]]), na.rm = TRUE))
  )
write_csv(moe_summary, "app/data/acs_moe_summary.csv")
write_csv(tab("perm_vs_analytic_agreement.csv"),      "app/data/perm_vs_analytic_agreement.csv")

# ---- Models ------------------------------------------------------------------------------
write_csv(tab("model_comparison.csv"),                "app/data/model_comparison.csv")
write_csv(tab("model_residual_diagnostics.csv"),      "app/data/model_diagnostics.csv")
write_csv(bind_rows(tab("model_coefficients_ols.csv") %>% mutate(weights = "queen"),
                    tab("model_coefficients_spatial.csv")),
          "app/data/model_coefficients.csv")
write_csv(tab("model_ols_residuals.csv"),             "app/data/model_ols_residuals.csv")

# ---- Metadata: provenance of this build ----------------------------------------------------
meta <- list(
  built_at      = format(Sys.time(), "%Y-%m-%d %H:%M:%S %Z"),
  acs_windows   = YEARS,
  acs_note      = "ACS 5-year estimates; windows end in the listed years",
  indicators    = INDICATORS,
  parameters    = list(seed = SEED, n_permutations = N_PERM, stability_draws = N_SIM,
                       stability_permutations = STAB_PERM, alpha = ALPHA, moe_confidence = 0.90),
  r_version     = R.version.string,
  packages      = as.list(setNames(
    vapply(c("sf", "spdep", "spatialreg", "dplyr", "tidycensus"),
           function(p) tryCatch(as.character(packageVersion(p)), error = function(e) NA_character_),
           character(1)),
    c("sf", "spdep", "spatialreg", "dplyr", "tidycensus")))
)
write_json(meta, "app/data/metadata.json", auto_unbox = TRUE, pretty = TRUE, na = "null")

message("Exported ", length(list.files("app/data")), " files to app/data/")
