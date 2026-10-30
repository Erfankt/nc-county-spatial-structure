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

# ---- ACS variables: detail tables (B/C-prefix) -------------------------------
# Pulled together via get_acs(variables = ACS_VARS); tidycensus hits the
# "detailed tables" endpoint for all of these in one call.
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
  edu_phd        = "B15003_025",

  # -- Phase 1 additions (see Census Variable Catalog doc) --------------------
  gini           = "B19083_001",   # Gini index of income inequality (ready-made)

  # % 65 and over: sum the 65+ age/sex bins over total population (B01001)
  age_m65_66     = "B01001_020",
  age_m67_69     = "B01001_021",
  age_m70_74     = "B01001_022",
  age_m75_79     = "B01001_023",
  age_m80_84     = "B01001_024",
  age_m85p       = "B01001_025",
  age_f65_66     = "B01001_044",
  age_f67_69     = "B01001_045",
  age_f70_74     = "B01001_046",
  age_f75_79     = "B01001_047",
  age_f80_84     = "B01001_048",
  age_f85p       = "B01001_049",

  med_gross_rent = "B25064_001",   # median gross rent (ready-made)

  # % renters cost-burdened (30%+ of income on rent): B25070 bins
  rentburd_total = "B25070_001",
  rentburd_30_34 = "B25070_007",
  rentburd_35_39 = "B25070_008",
  rentburd_40_49 = "B25070_009",
  rentburd_50p   = "B25070_010",

  # % seasonal/recreational housing units
  vacant_total    = "B25002_001",
  vacant_seasonal = "B25004_006",

  # % mobile homes
  units_total  = "B25024_001",
  units_mobile = "B25024_010",

  # % zero-vehicle households
  veh_total = "B08201_001",
  veh_zero  = "B08201_002",

  # % worked from home
  commute_total = "B08301_001",
  commute_wfh   = "B08301_021",

  # % foreign-born
  foreign_total = "B05002_001",
  foreign_born  = "B05002_013",

  # % non-Hispanic Black
  race_total = "B03002_001",
  race_black = "B03002_004"
)

# ---- ACS variables: subject tables (S-prefix) --------------------------------
# Pre-computed percentages; pulled in a separate get_acs() call because the
# Census API's subject-table endpoint is distinct from the detailed-table one.
# NOTE: the variable ID for "percent uninsured" (S2701) is NOT stable across
# vintages -- it is column C03 in the 2012 ACS5 release and C05 from 2017
# onward. 01_data.R's subject_vars_for_year() picks the right one per window;
# this constant is intentionally not used directly in the pull.

# ---- ACS variables: data profile tables (DP-prefix) --------------------------
# Also pre-computed percentages, also a separate endpoint from detailed tables.
PROFILE_VARS <- c(
  pct_manuf = "DP03_0035P"   # percent of civilian employed 16+ in manufacturing
)

# ---- Indicators analysed ------------------------------------------------------
INDICATORS <- tibble::tibble(
  name    = c("poverty_rate", "unemp_rate", "ba_plus_rate", "med_hh_income", "med_age", "med_home_value",
              "gini_index", "pct_65_plus", "med_gross_rent", "pct_renters_cost_burdened",
              "pct_seasonal_units", "pct_mobile_homes", "pct_zero_vehicle", "pct_work_from_home",
              "pct_uninsured", "pct_manufacturing", "pct_foreign_born", "pct_black"),
  label   = c("Poverty rate", "Unemployment rate", "Bachelor's degree or higher (25+)",
              "Median household income ($)", "Median age (years)", "Median home value ($)",
              "Gini index of income inequality", "Population 65 and over (%)", "Median gross rent ($)",
              "Renters cost-burdened, 30%+ of income (%)", "Seasonal/recreational housing units (%)",
              "Mobile homes (%)", "Zero-vehicle households (%)", "Worked from home (%)",
              "Uninsured (%)", "Employed in manufacturing (%)", "Foreign-born (%)",
              "Non-Hispanic Black (%)"),
  is_rate = c(TRUE, TRUE, TRUE, FALSE, FALSE, FALSE,
              FALSE, TRUE, FALSE, TRUE,
              TRUE, TRUE, TRUE, TRUE,
              TRUE, TRUE, TRUE, TRUE)
)

# ---- Output folders -----------------------------------------------------------
for (d in c("data/derived", "outputs/tables", "outputs/figures")) {
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
}
