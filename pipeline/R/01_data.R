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

pull_year <- function(yr) {
  message("Downloading ACS 5-year ", yr, " ...")
  get_acs(
    geography = "county", state = "NC", variables = ACS_VARS,
    year = yr, survey = "acs5", output = "wide"
  ) %>% mutate(year = yr)
}
raw <- map_dfr(YEARS, pull_year)

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
    med_home_value = med_home_valueE, med_home_value_moe = med_home_valueM
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
