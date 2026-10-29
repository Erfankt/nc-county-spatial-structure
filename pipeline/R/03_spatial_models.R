# 03_spatial_models.R
# Question: after accounting for county characteristics, is there residual spatial dependence,
# and do spatial lag / error / Durbin models fit better than OLS?
#
# Outcome: poverty rate (latest ACS window). Predictors are standardised (z-scores), so
# coefficients are the change in poverty rate per 1 SD of the predictor.
# Income is deliberately excluded from the predictors (it is nearly a mechanical function of poverty).

source("pipeline/R/00_config.R")
source("pipeline/R/helpers.R")

ind  <- readRDS("data/derived/nc_county_indicators.rds")
geom <- readRDS("data/derived/nc_county_geometry.rds") %>% arrange(GEOID)

yr <- max(YEARS)
d  <- ind[ind$year == yr, ]
d  <- d[match(geom$GEOID, d$GEOID), ] %>%
  mutate(log_pop = log(pop), log_home_value = log(med_home_value)) %>%
  mutate(across(c(ba_plus_rate, unemp_rate, med_age, log_pop, log_home_value),
                ~ as.numeric(scale(.x)), .names = "{.col}_z"))

f <- poverty_rate ~ ba_plus_rate_z + unemp_rate_z + med_age_z + log_pop_z + log_home_value_z

weights_list <- list(
  queen = build_queen_lw(geom),
  knn5  = build_knn_lw(geom, 5)
)

lm_tests <- if (exists("lm.RStests", envir = asNamespace("spdep"))) spdep::lm.RStests else spdep::lm.LMtests

set.seed(SEED)
ols <- lm(f, data = d)
write_csv(
  as_tibble(summary(ols)$coefficients, rownames = "term") %>% mutate(model = "OLS"),
  "outputs/tables/model_coefficients_ols.csv"
)
writeLines(capture.output(summary(ols)), "outputs/tables/model_ols_summary.txt")

fit_one <- function(wname, lw) {
  message("Fitting models with ", wname, " weights ...")

  # Diagnostics on OLS residuals
  mi    <- lm.morantest(ols, lw, zero.policy = TRUE)
  lmt   <- lm_tests(ols, lw, test = "all", zero.policy = TRUE)
  diag  <- tibble(
    weights = wname,
    test    = c("Moran's I on OLS residuals", names(lmt)),
    statistic = c(unname(mi$estimate[1]), map_dbl(lmt, ~ unname(.x$statistic))),
    p_value   = c(mi$p.value, map_dbl(lmt, ~ .x$p.value))
  )

  sar <- lagsarlm(f, data = d, listw = lw, zero.policy = TRUE)                  # spatial lag
  sem <- errorsarlm(f, data = d, listw = lw, zero.policy = TRUE)                # spatial error
  sdm <- lagsarlm(f, data = d, listw = lw, type = "mixed", zero.policy = TRUE)  # spatial Durbin

  models <- list(OLS = ols, SAR_lag = sar, SEM_error = sem, SDM_durbin = sdm)
  resid_moran <- map(models, ~ moran.mc(residuals(.x), lw, nsim = 999, zero.policy = TRUE))

  comp <- tibble(
    weights = wname,
    model   = names(models),
    AIC     = map_dbl(models, AIC),
    logLik  = map_dbl(models, ~ as.numeric(logLik(.x))),
    spatial_param = c(NA, sar$rho, sem$lambda, sdm$rho),
    spatial_param_name = c(NA, "rho", "lambda", "rho"),
    resid_moran_I = map_dbl(resid_moran, ~ unname(.x$statistic)),
    resid_moran_p = map_dbl(resid_moran, ~ .x$p.value)
  )

  coefs <- bind_rows(
    as_tibble(summary(sar)$Coef, rownames = "term") %>% mutate(model = "SAR_lag"),
    as_tibble(summary(sem)$Coef, rownames = "term") %>% mutate(model = "SEM_error"),
    as_tibble(summary(sdm)$Coef, rownames = "term") %>% mutate(model = "SDM_durbin")
  ) %>% mutate(weights = wname)

  # Direct / indirect / total effects for the lag model (needed to interpret rho)
  imp <- impacts(sar, listw = lw, R = 999)
  writeLines(
    c(capture.output(summary(sar)), "", "---- Impacts (SAR lag model) ----",
      capture.output(summary(imp, zstats = TRUE, short = TRUE))),
    sprintf("outputs/tables/model_sar_summary_%s.txt", wname)
  )

  list(diag = diag, comp = comp, coefs = coefs)
}

fits <- imap(weights_list, ~ fit_one(.y, .x))
write_csv(map_dfr(fits, "diag"),  "outputs/tables/model_residual_diagnostics.csv")
write_csv(map_dfr(fits, "comp"),  "outputs/tables/model_comparison.csv")
write_csv(map_dfr(fits, "coefs"), "outputs/tables/model_coefficients_spatial.csv")

print(map_dfr(fits, "diag"))
print(map_dfr(fits, "comp"))

# Export OLS residuals (used by the web app's residual map)
write_csv(tibble(GEOID = geom$GEOID, NAME = geom$NAME, ols_resid = as.numeric(residuals(ols))),
          "outputs/tables/model_ols_residuals.csv")

# Residual map from OLS: where does the non-spatial model miss?
d_res <- geom %>% mutate(ols_resid = residuals(ols))
p_res <- ggplot(d_res) +
  geom_sf(aes(fill = ols_resid), colour = "white", linewidth = 0.15) +
  scale_fill_gradient2(low = "#2166ac", mid = "white", high = "#b2182b", midpoint = 0,
                       name = "OLS residual") +
  labs(title = paste0("OLS residuals: poverty rate, ", yr),
       subtitle = "Clustering of residuals indicates unmodelled spatial dependence") +
  theme_map()
ggsave("outputs/figures/ols_residuals_map.png", p_res, width = 8, height = 4.5, dpi = 200)

message("03_spatial_models.R complete.")
