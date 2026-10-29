# install_packages.R -- one-time setup of the R packages used by the pipeline.
# Run from the repository root:  Rscript pipeline/install_packages.R
#
# For exact reproducibility you can additionally pin versions with renv:
#   install.packages("renv"); renv::init()   # then commit renv.lock

pkgs <- c(
  "tidycensus", "tigris",              # Census data + boundaries (step 01 only)
  "sf", "dplyr", "tidyr", "purrr", "readr", "ggplot2", "jsonlite",
  "spdep", "spatialreg",               # spatial weights, Moran's I, spatial regression
  "testthat"                           # tests
)
missing <- setdiff(pkgs, rownames(installed.packages()))
if (length(missing)) install.packages(missing)
message("All required packages installed.")
