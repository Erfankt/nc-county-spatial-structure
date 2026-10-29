# Unit tests for the spatial helpers, using a synthetic 8 x 8 grid of counties (no network, no API key).
# testthat runs from tests/testthat/, so move to the repository root for the sourced scripts.

withr::local_dir(normalizePath(file.path(testthat::test_path(), "..", "..")))
source("pipeline/R/00_config.R")
source("pipeline/R/helpers.R")

make_grid <- function(n = 8) {
  g <- st_make_grid(st_bbox(c(xmin = 0, ymin = 0, xmax = n, ymax = n)), n = c(n, n))
  st_sf(GEOID = sprintf("%03d", seq_along(g)), geometry = g)
}

test_that("queen contiguity gives 3 / 5 / 8 neighbours for corner / edge / interior cells", {
  geom <- make_grid()
  lw <- build_queen_lw(geom)
  card_n <- card(lw$neighbours)
  expect_equal(sort(unique(card_n)), c(3, 5, 8))
  expect_equal(sum(card_n == 3), 4)          # four corners
  expect_equal(sum(card_n == 5), 4 * 6)      # edges excluding corners
  expect_equal(sum(card_n == 8), 6 * 6)      # interior
  # row-standardised weights sum to one per row
  expect_true(all(abs(sapply(lw$weights, sum) - 1) < 1e-12))
})

test_that("kNN weights give every unit exactly k neighbours", {
  lw <- build_knn_lw(make_grid(), k = 5)
  expect_true(all(card(lw$neighbours) == 5))
})

test_that("quadrant labels follow the sign of the value and of its spatial lag", {
  geom <- make_grid(); lw <- build_queen_lw(geom)
  x <- rep(0, 64); x[geom$GEOID %in% sprintf("%03d", c(1:3, 9:11, 17:19))] <- 10  # 3x3 high block
  q <- quadrant(x + seq(0, 0.01, length.out = 64), lw)
  expect_true(all(q %in% c("High-High", "Low-Low", "High-Low", "Low-High")))
  expect_equal(q[10], "High-High")           # centre of the high block
  expect_equal(q[64], "Low-Low")             # far corner
})

test_that("a planted hot spot is detected as High-High and noise alone is not", {
  geom <- make_grid(); lw <- build_queen_lw(geom)
  set.seed(1)
  x <- rnorm(64, 0, 0.2)
  block <- geom$GEOID %in% sprintf("%03d", c(1:3, 9:11, 17:19))
  x[block] <- x[block] + 3
  res <- classify_local(x, lw, method = "analytic")
  expect_equal(as.character(res$cluster_fdr[10]), "High-High")

  set.seed(2)
  noise <- rnorm(64)
  res0 <- classify_local(noise, lw, method = "analytic")
  expect_lte(sum(res0$cluster_fdr != "Not significant"), 2)   # FDR controls false positives
})

test_that("classify_local returns well-formed output (permutation method)", {
  geom <- make_grid(); lw <- build_queen_lw(geom)
  set.seed(3)
  x <- as.numeric(scale(st_coordinates(st_centroid(st_geometry(geom)))[, 1])) + rnorm(64, 0, 0.3)  # smooth gradient
  res <- classify_local(x, lw, method = "perm", nsim = 499)
  expect_equal(nrow(res), 64)
  expect_true(all(res$p_value >= 0 & res$p_value <= 1))
  expect_true(all(res$p_fdr >= res$p_value - 1e-12))          # FDR-adjusted p never smaller than raw p
  expect_equal(levels(res$cluster_fdr), CLUSTER_LEVELS)
  # counties flagged after FDR are always flagged before adjustment
  expect_true(all(res$cluster_raw[res$cluster_fdr != "Not significant"] != "Not significant"))
})

test_that("global Moran's I is high for a smooth gradient and near zero for noise", {
  geom <- make_grid(); lw <- build_queen_lw(geom)
  grad <- st_coordinates(st_centroid(st_geometry(geom)))[, 1]
  expect_gt(moran(grad, lw, 64, Szero(lw))$I, 0.8)
  set.seed(4)
  expect_lt(abs(moran(rnorm(64), lw, 64, Szero(lw))$I), 0.3)
})
