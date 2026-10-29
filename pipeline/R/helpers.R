# helpers.R -- spatial weights, local Moran classification, plotting helpers

CLUSTER_LEVELS <- c("High-High", "Low-Low", "High-Low", "Low-High", "Not significant")
CLUSTER_COLS   <- c("High-High" = "#b2182b", "Low-Low" = "#2166ac",
                    "High-Low" = "#ef8a62", "Low-High" = "#67a9cf",
                    "Not significant" = "grey90")

# Queen-contiguity, row-standardised weights
build_queen_lw <- function(geom) {
  nb <- poly2nb(geom, queen = TRUE)
  nb2listw(nb, style = "W", zero.policy = TRUE)
}

# k-nearest-neighbour weights from county centroids (used as a sensitivity check)
build_knn_lw <- function(geom, k = 5) {
  cc <- suppressWarnings(st_coordinates(st_centroid(st_geometry(geom))))
  nb <- knn2nb(knearneigh(cc, k = k))
  nb2listw(nb, style = "W")
}

# Moran scatterplot quadrant of each unit (sign of z and spatial lag of z)
quadrant <- function(x, lw) {
  z    <- as.numeric(scale(x))
  lagz <- lag.listw(lw, z, zero.policy = TRUE)
  dplyr::case_when(
    z >= 0 & lagz >= 0 ~ "High-High",
    z <  0 & lagz <  0 ~ "Low-Low",
    z >= 0 & lagz <  0 ~ "High-Low",
    TRUE               ~ "Low-High"
  )
}

# Local Moran's I with cluster labels.
#  method = "perm"     : conditional permutation p-values (headline results)
#  method = "analytic" : normal-theory p-values (fast; used inside Monte Carlo loops)
# Returns both unadjusted (cluster_raw) and FDR-adjusted (cluster_fdr) classifications.
classify_local <- function(x, lw, method = c("perm", "analytic"), nsim = N_PERM, alpha = ALPHA) {
  method <- match.arg(method)
  if (method == "perm") {
    res <- localmoran_perm(x, lw, nsim = nsim, zero.policy = TRUE, iseed = SEED)
    sim_col <- grep("Sim", colnames(res))[1]
    if (is.na(sim_col)) stop("Could not find the simulated p-value column in localmoran_perm output.")
    p <- as.numeric(res[, sim_col])
  } else {
    res <- localmoran(x, lw, zero.policy = TRUE)
    p   <- as.numeric(res[, 5])  # two-sided p-value
  }
  q     <- quadrant(x, lw)
  p_adj <- p.adjust(p, method = "fdr")
  tibble::tibble(
    local_I     = as.numeric(res[, 1]),
    p_value     = p,
    p_fdr       = p_adj,
    quadrant    = q,
    cluster_raw = factor(ifelse(p     < alpha, q, "Not significant"), levels = CLUSTER_LEVELS),
    cluster_fdr = factor(ifelse(p_adj < alpha, q, "Not significant"), levels = CLUSTER_LEVELS)
  )
}

# Pull one indicator column for a given year in the same order as the geometry
get_x <- function(ind, geom, yr, v) {
  d <- ind[ind$year == yr, ]
  d[match(geom$GEOID, d$GEOID), ][[v]]
}

theme_map <- function() {
  theme_void(base_size = 11) +
    theme(plot.title = element_text(face = "bold"), legend.position = "right")
}
