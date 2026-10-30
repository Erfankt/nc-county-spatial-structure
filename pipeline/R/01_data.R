# 01_data.R -- pull ACS 5-year county data for NC (with margins of error) for several years
# Output: data/derived/nc_county_indicators.rds / .csv, data/derived/nc_county_geometry.rds

source("pipeline/R/00_config.R")

# Only the download step needs the Census packages and an API key, so steps 02-04 run offline.
suppressPackageStartupMessages({ library(tidycensus); library(tigris) })
options(tigris_use_cache = TRUE)

# ---- Census API key: read from the environment, never hard-code it ----------
# One-time setup in R:  usethis::edit_r_environ()  and add the line:  CENSUS_API_KEY=your_key
# (Free key: https://api.census.gov/data/key_signup.html)
key <- Sys.getenv("CENSUS_API_KEY")
if (identical(key, "")) {
  stop("CENSUS_API_KEY is not set. Add it to ~/.Renviron (usethis::edit_r_environ()) and restart R.")
}
census_api_key(key)

# Detail tables (B/C-prefix) -- one endpoint, pulled together as before.
pull_year_detail <- function(yr) {
  message("Downloading ACS 5-year ", yr, " (detail tables) ...")
  get_acs(
    geography = "county", state = "NC", variables = ACS_VARS,
    year = yr, survey = "acs5", output = "wide"
  ) %>% mutate(year = yr)
}

# Subject tables (S-prefix) -- separate Census API endpoint from detail tables.
# NOTE: the Census Bureau redesigned S2701 between the 2012 and 2017 ACS5
# vintages. "Percent Uninsured" lives at column C03 in 2012 but moved to
# column C05 from 2017 onward (verified against the live API for all three
# windows this app uses). Pick the right variable ID per year rather than
# assuming SUBJECT_VARS is stable across vintages.
subject_vars_for_year <- function(yr) {
  uninsured_col <- if (yr <= 2012) "S2701_C03_001" else "S2701_C05_001"
  c(pct_uninsured = uninsured_col)
}

pull_year_subject <- function(yr) {
  message("Downloading ACS 5-year ", yr, " (subject tables) ...")
  get_acs(
    geography = "county", state = "NC", variables = subject_vars_for_year(yr),
    year = yr, survey = "acs5", output = "wide"
  ) %>% select(-NAME) %>% mutate(year = yr)
}

# Data profile tables (DP-prefix) -- also a separate endpoint.
pull_year_profile <- function(yr) {
  message("Downloading ACS 5-year ", yr, " (profile tables) ...")
  get_acs(
    geography = "county", state = "NC", variables = PROFILE_VARS,
    year = yr, survey = "acs5", output = "wide"
  ) %>% select(-NAME) %>% mutate(year = yr)
}

raw_detail  <- map_dfr(YEARS, pull_year_detail)
raw_subject <- map_dfr(YEARS, pull_year_subject)
raw_profile <- map_dfr(YEARS, pull_year_profile)

raw <- raw_detail %>%
  left_join(raw_subject, by = c("GEOID", "year")) %>%
  left_join(raw_profile, by = c("GEOID", "year"))

# Root-sum-of-squares MOE for a sum of estimates (row-wise)
moe_rowsum <- function(...) sqrt(rowSums(cbind(...)^2))

ind <- raw %>%
  transmute(
    GEOID, NAME, year,
    pop = popE, pop_moe = popM,

    poverty_rate     = pov_belowE / pov_totalE,
    poverty_rate_moe = moe_prop(pov_belowE, pov_totalE, pov_belowM, pov_totalM),

    unemp_rate     = unemployedE / lf_civE,
    unemp_rate_moe = moe_prop(unemployedE, lf_civE, unemployedM, lf_civM),

    ba_plus_rate = (edu_baE + edu_maE + edu_profE + edu_phdE) / edu_totalE,
    ba_plus_rate_moe = moe_prop(
      edu_baE + edu_maE + edu_profE + edu_phdE, edu_totalE,
      moe_rowsum(edu_baM, edu_maM, edu_profM, edu_phdM), edu_totalM
    ),

    med_hh_income = med_hh_incomeE, med_hh_income_moe = med_hh_incomeM,
    med_age       = med_ageE,       med_age_moe       = med_ageM,
    med_home_value = med_home_valueE, med_home_value_moe = med_home_valueM,

    # -- Phase 1 additions (see Census Variable Catalog doc) --------------------
    gini_index = giniE, gini_index_moe = giniM,

    pct_65_plus = (age_m65_66E + age_m67_69E + age_m70_74E + age_m75_79E + age_m80_84E + age_m85pE +
                   age_f65_66E + age_f67_69E + age_f70_74E + age_f75_79E + age_f80_84E + age_f85pE) / popE,
    pct_65_plus_moe = moe_prop(
      age_m65_66E + age_m67_69E + age_m70_74E + age_m75_79E + age_m80_84E + age_m85pE +
        age_f65_66E + age_f67_69E + age_f70_74E + age_f75_79E + age_f80_84E + age_f85pE,
      popE,
      moe_rowsum(age_m65_66M, age_m67_69M, age_m70_74M, age_m75_79M, age_m80_84M, age_m85pM,
                 age_f65_66M, age_f67_69M, age_f70_74M, age_f75_79M, age_f80_84M, age_f85pM),
      popM
    ),

    med_gross_rent = med_gross_rentE, med_gross_rent_moe = med_gross_rentM,

    pct_renters_cost_burdened = (rentburd_30_34E + rentburd_35_39E + rentburd_40_49E + rentburd_50pE) / rentburd_totalE,
    pct_renters_cost_burdened_moe = moe_prop(
      rentburd_30_34E + rentburd_35_39E + rentburd_40_49E + rentburd_50pE, rentburd_totalE,
      moe_rowsum(rentburd_30_34M, rentburd_35_39M, rentburd_40_49M, rentburd_50pM), rentburd_totalM
    ),

    pct_seasonal_units = vacant_seasonalE / vacant_totalE,
    pct_seasonal_units_moe = moe_prop(vacant_seasonalE, vacant_totalE, vacant_seasonalM, vacant_totalM),

    pct_mobile_homes = units_mobileE / units_totalE,
    pct_mobile_homes_moe = moe_prop(units_mobileE, units_totalE, units_mobileM, units_totalM),

    pct_zero_vehicle = veh_zeroE / veh_totalE,
    pct_zero_vehicle_moe = moe_prop(veh_zeroE, veh_totalE, veh_zeroM, veh_totalM),

    pct_work_from_home = commute_wfhE / commute_totalE,
    pct_work_from_home_moe = moe_prop(commute_wfhE, commute_totalE, commute_wfhM, commute_totalM),

    # S2701/DP03 percent variables arrive on a 0-100 scale; the app expects 0-1 fractions.
    pct_uninsured = pct_uninsuredE / 100, pct_uninsured_moe = pct_uninsuredM / 100,
    pct_manufacturing = pct_manufE / 100, pct_manufacturing_moe = pct_manufM / 100,

    pct_foreign_born = foreign_bornE / foreign_totalE,
    pct_foreign_born_moe = moe_prop(foreign_bornE, foreign_totalE, foreign_bornM, foreign_totalM),

    pct_black = race_blackE / race_totalE,
    pct_black_moe = moe_prop(race_blackE, race_totalE, race_blackM, race_totalM)
  )

# County geometry (cartographic boundary), projected to NC State Plane (meters)
geom <- counties(state = "NC", cb = TRUE, year = 2022) %>%
  select(GEOID, NAME) %>%
  st_transform(32119) %>%
  arrange(GEOID)

stopifnot(nrow(geom) == 100, all(geom$GEOID %in% ind$GEOID))

saveRDS(ind,  "data/derived/nc_county_indicators.rds")
write_csv(ind, "data/derived/nc_county_indicators.csv")
saveRDS(geom, "data/derived/nc_county_geometry.rds")
