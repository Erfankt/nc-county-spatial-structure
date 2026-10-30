# 02_spatial_structure.R
# Question: is there statistically defensible spatial structure in NC county socioeconomic
# conditions, has it changed over time, and does it survive ACS sampling error?
#
#  A0. Estimate reliability: ACS coefficient-of-variation tiers
#  A.  Global Moran's I (permutation inference) by indicator and year
#  B.  Local Moran's I (LISA) with conditional-permutation p-values and FDR correction
#  C.  Cluster persistence across the three ACS windows
#  D.  Margin-of-error stability: re-draw each county estimate from its ACS sampling distribution
#      and measure how often each county keeps its cluster label and how much global I varies
#  D1. Evidence grade: synthesis of reliability tier, FDR significance, and MOE stability
#  E.  Sensitivity of global Moran's I to the spatial-weights definition
#  F.  Spatial correlogram: Moran's I by contiguity order (reach of the spatial pattern)
#  G.  Bivariate LISA: cross-indicator spatial association for three key pairs

source("pipeline/R/00_config.R")
source("pipeline/R/helpers.R")

ind  <- readRDS("data/derived/nc_county_indicators.rds")
geom <- readRDS("data/derived/nc_county_geometry.rds") %>% arrange(GEOID)
lw   <- build_queen_lw(geom)

message("Queen contiguity: ", length(lw$neighbours), " counties, ",
        sum(card(lw$neighbours) == 0), " isolates, mean neighbours = ",
        round(mean(card(lw$neighbours)), 2))

# ---- A0. Estimate reliability: ACS coefficient-of-variation tiers ---------------
# CV = se / |estimate|, where se = MOE / 1.645 (ACS 90 % CI).
# Tiers follow the Census Bureau's own guidance:
#   Reliable        CV < 12 %
#   Use with caution  12 – 40 %
#   Unreliable      CV > 40 %
message("A0. Computing CV reliability tiers...")
cv_tbl <- expand_grid(year = YEARS, indicator = INDICATORS$name) %>%
  mutate(res = map2(year, indicator, function(yr, v) {
    d   <- ind[ind$year == yr, ]
    d   <- d[match(geom$GEOID, d$GEOID), ]
    E   <- d[[v]]
    moe <- d[[paste0(v, "_moe")]]
    tibble(
      GEOID    = geom$GEOID,
      NAME     = geom$NAME,
      estimate = E,
      moe      = moe,
      cv_pct   = abs(moe / Z90 / E) * 100,
      cv_tier  = cv_tier(E, moe)
    )
  })) %>%
  unnest(res)
write_csv(cv_tbl, "outputs/tables/cv_tiers.csv")

# Summary: share of counties by tier per indicator/window
cv_summary <- cv_tbl %>%
  count(year, indicator, cv_tier) %>%
  group_by(year, indicator) %>%
  mutate(share = n / sum(n)) %>%
  ungroup() %>%
  left_join(INDICATORS %>% select(indicator = name, label), by = "indicator")
write_csv(cv_summary, "outputs/tables/cv_tier_summary.csv")
print(cv_summary %>% filter(cv_tier == "Unreliable") %>% arrange(year, indicator))

# ---- A. Global Moran's I -------------------------------------------------------
set.seed(SEED)
global_tbl <- expand_grid(year = YEARS, indicator = INDICATORS$name) %>%
  mutate(res = map2(year, indicator, function(yr, v) {
    x  <- get_x(ind, geom, yr, v)
    mc <- moran.mc(x, lw, nsim = N_PERM, zero.policy = TRUE)
    tibble(moran_I = unname(mc$statistic), p_value = mc$p.value)
  })) %>%
  unnest(res) %>%
  left_join(INDICATORS %>% select(indicator = name, label), by = "indicator")
write_csv(global_tbl, "outputs/tables/global_moran_by_year.csv")
print(global_tbl)

p_global <- ggplot(global_tbl, aes(factor(year), moran_I, group = label, colour = label)) +
  geom_line(linewidth = 0.8) + geom_point(aes(shape = p_value < ALPHA), size = 2.5) +
  scale_shape_manual(values = c(`TRUE` = 16, `FALSE` = 1), name = paste0("p < ", ALPHA)) +
  labs(x = "ACS 5-year window (end year)", y = "Global Moran's I", colour = NULL,
       title = "Spatial autocorrelation of NC county indicators over time",
       subtitle = paste0("Queen contiguity, ", N_PERM, " permutations")) +
  theme_minimal(base_size = 11)
ggsave("outputs/figures/global_moran_over_time.png", p_global, width = 8, height = 5, dpi = 200)

# ---- B. Local Moran's I (permutation + FDR) ------------------------------------
set.seed(SEED)
local_tbl <- expand_grid(year = YEARS, indicator = INDICATORS$name) %>%
  mutate(res = map2(year, indicator, function(yr, v) {
    x <- get_x(ind, geom, yr, v)
    classify_local(x, lw, method = "perm") %>% mutate(GEOID = geom$GEOID, value = x)
  })) %>%
  unnest(res) %>%
  left_join(st_drop_geometry(geom), by = "GEOID")
write_csv(local_tbl, "outputs/tables/local_moran_clusters_all_years.csv")

cluster_counts <- local_tbl %>%
  count(year, indicator, cluster_raw, cluster_fdr) %>%
  arrange(indicator, year)
write_csv(cluster_counts, "outputs/tables/local_moran_cluster_counts.csv")

plot_cluster_map <- function(v, yr, col = "cluster_fdr", title_suffix = "FDR-adjusted") {
  lab <- INDICATORS$label[INDICATORS$name == v]
  d <- geom %>% left_join(local_tbl %>% filter(indicator == v, year == yr), by = c("GEOID", "NAME"))
  ggplot(d) +
    geom_sf(aes(fill = .data[[col]]), colour = "white", linewidth = 0.15) +
    scale_fill_manual(values = CLUSTER_COLS, drop = FALSE, name = "Local Moran cluster") +
    labs(title = paste0(lab, " -- ", yr), subtitle = paste0("LISA clusters (", title_suffix, ", p < ", ALPHA, ")")) +
    theme_map()
}
for (v in INDICATORS$name) {
  ggsave(sprintf("outputs/figures/lisa_%s_%d_fdr.png", v, max(YEARS)),
         plot_cluster_map(v, max(YEARS), "cluster_fdr", "FDR-adjusted"), width = 8, height = 4.5, dpi = 200)
  ggsave(sprintf("outputs/figures/lisa_%s_%d_unadjusted.png", v, max(YEARS)),
         plot_cluster_map(v, max(YEARS), "cluster_raw", "unadjusted"), width = 8, height = 4.5, dpi = 200)
}

# Moran scatterplots for the latest window
scatter_df <- map_dfr(INDICATORS$name, function(v) {
  x <- get_x(ind, geom, max(YEARS), v)
  tibble(indicator = v, GEOID = geom$GEOID, NAME = geom$NAME,
         z = as.numeric(scale(x)), lag_z = lag.listw(lw, as.numeric(scale(x)), zero.policy = TRUE))
}) %>% left_join(INDICATORS %>% select(indicator = name, label), by = "indicator")
p_scatter <- ggplot(scatter_df, aes(z, lag_z)) +
  geom_hline(yintercept = 0, colour = "grey60") + geom_vline(xintercept = 0, colour = "grey60") +
  geom_point(alpha = 0.7) + geom_smooth(method = "lm", se = FALSE, colour = "firebrick", linewidth = 0.7) +
  facet_wrap(~label, scales = "free") +
  labs(x = "Standardised value", y = "Spatial lag (neighbour mean)",
       title = paste0("Moran scatterplots, ACS ", max(YEARS))) +
  theme_minimal(base_size = 10)
ggsave("outputs/figures/moran_scatterplots.png", p_scatter, width = 10, height = 6.5, dpi = 200)

# ---- C. Cluster persistence across windows -------------------------------------
persistence <- local_tbl %>%
  filter(cluster_fdr != "Not significant") %>%
  group_by(indicator, GEOID, NAME, cluster_fdr) %>%
  summarise(n_windows = n(), windows = paste(year, collapse = ", "), .groups = "drop") %>%
  arrange(indicator, desc(n_windows), cluster_fdr, NAME)
write_csv(persistence, "outputs/tables/cluster_persistence.csv")

# ---- D. Margin-of-error stability (every window) -------------------------------
# For each draw, every county's value is resampled from Normal(estimate, (MOE/1.645)^2)
# (ACS MOEs are 90% intervals), clipped to [0, 1] for rates, and LISA is recomputed with
# conditional permutation (STAB_PERM permutations).
#
# Stability is measured with UNADJUSTED permutation p < ALPHA, not FDR: BH/FDR correction at
# n = 100 needs p-values near 1/N_PERM, which a 999-permutation run inside a Monte Carlo loop
# cannot resolve (it would almost never flag anything). So "stable" here means: the county keeps
# the same cluster type at nominal p < 0.05 under resampling. That is a weaker criterion than the
# FDR headline, and a county that fails even this test is clearly fragile.
mc_stability <- function(v, yr = max(YEARS), nsim = N_SIM) {
  d  <- ind[ind$year == yr, ]
  d  <- d[match(geom$GEOID, d$GEOID), ]
  E  <- d[[v]]
  se <- d[[paste0(v, "_moe")]] / Z90
  se[is.na(se)] <- 0
  is_rate <- INDICATORS$is_rate[INDICATORS$name == v]
  n <- length(E)

  head_tbl <- local_tbl %>% filter(indicator == v, year == yr) %>% arrange(match(GEOID, geom$GEOID))
  base_fdr <- as.character(head_tbl$cluster_fdr)
  base_raw <- as.character(head_tbl$cluster_raw)
  analytic_base <- as.character(classify_local(E, lw, method = "analytic")$cluster_fdr)

  # Draw ALL resampled datasets up front. classify_local(method = "perm") calls set.seed(SEED)
  # internally (localmoran_perm's iseed), which would otherwise reset the RNG every iteration
  # and make every draw identical.
  draws <- matrix(rnorm(n * nsim, mean = E, sd = se), nrow = n, ncol = nsim)
  if (is_rate) draws <- pmin(pmax(draws, 0), 1)

  sim_class <- matrix(NA_character_, n, nsim)
  sim_p     <- matrix(NA_real_, n, nsim)
  sim_I     <- numeric(nsim)
  for (s in seq_len(nsim)) {
    xs  <- draws[, s]
    res <- classify_local(xs, lw, method = "perm", nsim = STAB_PERM)
    sim_class[, s] <- as.character(res$cluster_raw)
    sim_p[, s]     <- res$p_value
    sim_I[s] <- moran(xs, lw, n, Szero(lw), zero.policy = TRUE)$I
  }
  list(
    county = tibble(
      year = yr, indicator = v, GEOID = geom$GEOID, NAME = geom$NAME,
      cluster_headline_fdr = base_fdr,
      cluster_headline_raw = base_raw,
      cluster_analytic     = analytic_base,
      share_draws_same_raw_class  = rowMeans(sim_class == matrix(base_raw, n, nsim)),
      share_draws_raw_significant = rowMeans(sim_class != "Not significant"),
      median_perm_p = apply(sim_p, 1, median)
    ),
    global = tibble(
      year = yr, indicator = v,
      moran_I_point = moran(E, lw, n, Szero(lw), zero.policy = TRUE)$I,
      moran_I_sim_mean = mean(sim_I),
      moran_I_sim_p05 = unname(quantile(sim_I, 0.05)),
      moran_I_sim_p95 = unname(quantile(sim_I, 0.95))
    )
  )
}

# The seed is reset for each window so the 2022 results are identical whether or not the
# earlier windows are run.
stab <- list()
for (yr in YEARS) {
  set.seed(SEED)
  stab <- c(stab, map(INDICATORS$name, mc_stability, yr = yr))
}
stab_county <- map_dfr(stab, "county")
stab_global <- map_dfr(stab, "global") %>% left_join(INDICATORS %>% select(indicator = name, label), by = "indicator")
write_csv(stab_county, "outputs/tables/moe_cluster_stability_county.csv")
write_csv(stab_global, "outputs/tables/moe_global_moran_uncertainty.csv")
print(stab_global)

# Stability of the clusters that are significant (FDR) in the headline results
stab_sig <- stab_county %>% filter(cluster_headline_fdr != "Not significant") %>%
  arrange(year, indicator, desc(share_draws_same_raw_class))
write_csv(stab_sig, "outputs/tables/moe_stability_of_headline_clusters.csv")
print(stab_sig, n = Inf)

# Stability of ALL nominally significant (unadjusted) clusters, for context
stab_raw <- stab_county %>% filter(cluster_headline_raw != "Not significant") %>%
  arrange(year, indicator, desc(share_draws_same_raw_class))
write_csv(stab_raw, "outputs/tables/moe_stability_of_unadjusted_clusters.csv")

# Agreement between permutation-based and analytic classification (transparency check)
agree <- stab_county %>% group_by(year, indicator) %>%
  summarise(agreement_perm_vs_analytic = mean(cluster_headline_fdr == cluster_analytic), .groups = "drop")
write_csv(agree, "outputs/tables/perm_vs_analytic_agreement.csv")
print(agree)

for (v in INDICATORS$name) {
  lab <- INDICATORS$label[INDICATORS$name == v]
  d <- geom %>% left_join(stab_county %>% filter(indicator == v, year == max(YEARS)), by = c("GEOID", "NAME"))
  p <- ggplot(d) +
    geom_sf(aes(fill = share_draws_raw_significant), colour = "white", linewidth = 0.15) +
    scale_fill_viridis_c(limits = c(0, 1), name = "Share of draws\nnominally significant") +
    labs(title = paste0(lab, " -- how often each county is a nominally significant LISA cluster"),
         subtitle = paste0(N_SIM, " draws from estimate +/- MOE, ", max(YEARS), " window, unadjusted p < ", ALPHA)) +
    theme_map()
  ggsave(sprintf("outputs/figures/stability_%s_%d.png", v, max(YEARS)), p, width = 8, height = 4.5, dpi = 200)
}

# ---- D1. Evidence grade: reliability × FDR × stability -------------------------
# Each county × indicator × window gets one of five ordered grades:
#   Unreliable estimate  CV > 40 %: the estimate is too noisy to classify
#   No cluster           estimate usable but no spatial association detected
#   Nominal only         significant at unadjusted p < 0.05 but not after FDR
#   FDR-significant      passes Benjamini-Hochberg correction
#   Robust               FDR-significant AND same label under analytic test AND ≥ 90 % stable
message("D1. Computing evidence grades...")
evidence_tbl <- cv_tbl %>%
  select(year, indicator, GEOID, NAME, cv_tier) %>%
  left_join(local_tbl %>% select(year, indicator, GEOID, cluster_raw, cluster_fdr),
            by = c("year", "indicator", "GEOID")) %>%
  left_join(stab_county %>% select(year, indicator, GEOID, cluster_analytic,
                                    share_draws_same_raw_class),
            by = c("year", "indicator", "GEOID")) %>%
  mutate(
    grade = case_when(
      cv_tier == "Unreliable"  ~ "Unreliable estimate",
      cluster_fdr == "Not significant" & cluster_raw == "Not significant" ~ "No cluster",
      cluster_fdr == "Not significant" ~ "Nominal only",
      cluster_analytic == as.character(cluster_fdr) &
        share_draws_same_raw_class >= 0.90 ~ "Robust",
      TRUE ~ "FDR-significant"
    ),
    grade = factor(grade, levels = GRADE_LEVELS)
  )
write_csv(evidence_tbl, "outputs/tables/evidence_grades.csv")
message("Evidence grade distribution:")
print(evidence_tbl %>% count(grade) %>% arrange(desc(n)))

# ---- E. Sensitivity to the spatial-weights definition ----------------------------
lw_knn5 <- build_knn_lw(geom, 5)
lw_knn8 <- build_knn_lw(geom, 8)
sens <- expand_grid(indicator = INDICATORS$name, weights = c("queen", "knn5", "knn8")) %>%
  mutate(res = map2(indicator, weights, function(v, w) {
    x <- get_x(ind, geom, max(YEARS), v)
    l <- switch(w, queen = lw, knn5 = lw_knn5, knn8 = lw_knn8)
    mc <- moran.mc(x, l, nsim = N_PERM, zero.policy = TRUE)
    tibble(moran_I = unname(mc$statistic), p_value = mc$p.value)
  })) %>% unnest(res)
write_csv(sens, "outputs/tables/global_moran_weights_sensitivity.csv")
print(sens)

# ---- F. Spatial correlogram: Moran's I by contiguity order ----------------------
# Shows HOW FAR spatial dependence reaches.  At order k, a county's "neighbours"
# are those connected by exactly k queen-contiguity steps (non-cumulative).
# This answers: is the pattern local (drops off fast) or regional (persists to k = 4-5)?
# We use 999 permutations here (not N_PERM = 9999) for speed; patterns at k > 1 are
# typically wider and the null distribution is easier to approximate.
message("F. Computing spatial correlogram (contiguity orders 1–5)...")
set.seed(SEED)
MAX_LAG <- 5
corro <- expand_grid(year = YEARS, indicator = INDICATORS$name, order = seq_len(MAX_LAG)) %>%
  mutate(res = pmap(list(year, indicator, order), function(yr, v, k) {
    x    <- get_x(ind, geom, yr, v)
    lw_k <- build_higher_order_lw(lw, k)
    n_nb <- sum(card(lw_k$neighbours) > 0)    # counties with at least one order-k neighbour
    if (n_nb < 3L) {
      return(tibble(moran_I = NA_real_, p_value = NA_real_, n_pairs = 0L))
    }
    mc <- moran.mc(x, lw_k, nsim = 999, zero.policy = TRUE)
    tibble(moran_I = unname(mc$statistic), p_value = mc$p.value,
           n_pairs = as.integer(n_nb))
  })) %>%
  unnest(res) %>%
  left_join(INDICATORS %>% select(indicator = name, label), by = "indicator")
write_csv(corro, "outputs/tables/correlogram.csv")

p_corro <- ggplot(corro %>% filter(!is.na(moran_I)),
                  aes(order, moran_I, group = label, colour = label)) +
  geom_hline(yintercept = 0, colour = "grey70", linetype = "dashed") +
  geom_line(linewidth = 0.8) +
  geom_point(aes(shape = p_value < ALPHA), size = 2.5) +
  scale_shape_manual(values = c(`TRUE` = 16, `FALSE` = 1), name = paste0("p < ", ALPHA)) +
  scale_x_continuous(breaks = seq_len(MAX_LAG)) +
  facet_wrap(~factor(year), nrow = 1) +
  labs(x = "Contiguity order", y = "Global Moran's I", colour = NULL,
       title = "Spatial correlogram: how far does the clustering reach?",
       subtitle = "Queen contiguity; order k = counties exactly k steps away") +
  theme_minimal(base_size = 11)
ggsave("outputs/figures/correlogram.png", p_corro, width = 12, height = 4.5, dpi = 200)
print(corro %>% arrange(indicator, year, order) %>% select(-label))

# ---- G. Bivariate LISA: cross-indicator spatial association ----------------------
# Tests whether a county's value of indicator X correlates with its NEIGHBOURS'
# average value of indicator Y.  Uses localmoran_bv() from spdep (>= 1.2-1).
# Auto-generated: every unordered pair of indicators in INDICATORS$name, so the
# app's Bivariate LISA panel always offers the full set with no hardcoded list
# to maintain. Exclude a name here only if it is a log-transformed duplicate of
# another indicator already in the set (keep this in sync with _BVLISA_EXCLUDE
# in app/analysis.py).
BV_EXCLUDE <- character(0)
bv_candidates <- setdiff(INDICATORS$name, BV_EXCLUDE)
bv_pair_mat <- combn(bv_candidates, 2)
BV_PAIRS <- lapply(seq_len(ncol(bv_pair_mat)), function(i) {
  x <- bv_pair_mat[1, i]; y <- bv_pair_mat[2, i]
  list(x = x, y = y,
       label = paste0(INDICATORS$label[INDICATORS$name == x], " (focal) ~ ",
                       INDICATORS$label[INDICATORS$name == y], " (lag)"))
})
message("G. Computing bivariate LISA for ", length(BV_PAIRS), " pairs × ", length(YEARS), " windows...")
set.seed(SEED)
bv_tbl <- map_dfr(BV_PAIRS, function(pair) {
  map_dfr(YEARS, function(yr) {
    xi <- get_x(ind, geom, yr, pair$x)
    xj <- get_x(ind, geom, yr, pair$y)
    # localmoran_bv: focal variable xi, spatial lag of xj
    res   <- localmoran_bv(xi, xj, lw, nsim = N_PERM, zero.policy = TRUE, iseed = SEED)
    p_col <- grep("Pr\\(z", colnames(res), value = TRUE)[1]
    p     <- as.numeric(res[, p_col])
    p_adj <- p.adjust(p, method = "fdr")
    zi    <- as.numeric(scale(xi))
    zj    <- as.numeric(scale(xj))
    lag_zj <- lag.listw(lw, zj, zero.policy = TRUE)
    bv_quad <- dplyr::case_when(
      zi >= 0 & lag_zj >= 0 ~ "High-High",
      zi <  0 & lag_zj <  0 ~ "Low-Low",
      zi >= 0 & lag_zj <  0 ~ "High-Low",
      TRUE                  ~ "Low-High"
    )
    tibble(
      year = yr, x_var = pair$x, y_var = pair$y, pair_label = pair$label,
      GEOID = geom$GEOID, NAME = geom$NAME,
      local_I     = as.numeric(res[, 1]),
      p_value     = p,
      p_fdr       = p_adj,
      quadrant    = bv_quad,
      cluster_raw = factor(ifelse(p     < ALPHA, bv_quad, "Not significant"), levels = CLUSTER_LEVELS),
      cluster_fdr = factor(ifelse(p_adj < ALPHA, bv_quad, "Not significant"), levels = CLUSTER_LEVELS)
    )
  })
})
write_csv(bv_tbl, "outputs/tables/bivariate_lisa.csv")
bv_counts <- bv_tbl %>% filter(cluster_fdr != "Not significant") %>%
  count(year, pair_label, cluster_fdr) %>% arrange(pair_label, year)
print(bv_counts, n = Inf)

message("02_spatial_structure.R complete.")
