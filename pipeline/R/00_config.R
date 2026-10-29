# 00_config.R -- shared configuration for the NC county spatial-structure analysis
# Run everything from the REPOSITORY ROOT:  Rscript pipeline/run_all.R

suppressPackageStartupMessages({
  library(sf)
  library(dplyr)
  library(tidyr)
  library(purrr)
  library(readr)
  library(ggplot2)
  library(spdep)
  library(spatialreg)
})

# ---- Analysis parameters ------------------------------------------------------
YEARS  <- c(2012, 2017, 2022)  # ACS 5-year end years -> non-overlapping windows 2008-12, 2013-17, 2018-22
SEED   <- 42
N_SIM  <- 500                  # Monte Carlo draws for the margin-of-error stability analysis
STAB_PERM <- 999               # permutations per draw inside the stability loop
N_PERM <- 9999                 # permutations for Moran's I inference
ALPHA  <- 0.05
Z90    <- 1.645                # ACS margins of error are published at the 90% confidence level

# ---- ACS variables (raw tables) ----------------------------------------------
ACS_VARS <- c(
  pop            = "B01003_001",
  med_age        = "B01002_001",
  med_hh_income  = "B19013_001",
  med_home_value = "B25077_001",
  pov_total      = "B17001_001",
  pov_below      = "B17001_002",
  lf_civ         = "B23025_003",
  unemployed     = "B23025_005",
  edu_total      = "B15003_001",
  edu_ba         = "B15003_022",
  edu_ma         = "B15003_023",
  edu_prof       = "B15003_024",
  edu_phd        = "B15003_025"
)

# ---- Indicators analysed ------------------------------------------------------
INDICATORS <- tibble::tibble(
  name    = c("poverty_rate", "unemp_rate", "ba_plus_rate", "med_hh_income", "med_age", "med_home_value"),
  label   = c("Poverty rate", "Unemployment rate", "Bachelor's degree or higher (25+)",
              "Median household income ($)", "Median age (years)", "Median home value ($)"),
  is_rate = c(TRUE, TRUE, TRUE, FALSE, FALSE, FALSE)
)

# ---- Output folders -----------------------------------------------------------
for (d in c("data/derived", "outputs/tables", "outputs/figures")) {
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
}
