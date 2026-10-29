# run_all.R -- reproduce the full analysis and the app data.
# Run from the REPOSITORY ROOT:   Rscript pipeline/run_all.R
#
# Needs R >= 4.1 and the packages in pipeline/install_packages.R.
# Step 01 needs CENSUS_API_KEY (see README). Steps 02-04 run offline from data/derived/.
#
# Use SKIP_DOWNLOAD=1 to reuse an existing data/derived/ and skip the Census download:
#   SKIP_DOWNLOAD=1 Rscript pipeline/run_all.R

if (!identical(Sys.getenv("SKIP_DOWNLOAD"), "1")) source("pipeline/R/01_data.R")
source("pipeline/R/02_spatial_structure.R")
source("pipeline/R/03_spatial_models.R")
source("pipeline/R/04_export.R")
