if (.Platform$OS.type == "windows") Sys.setlocale("LC_CTYPE", "Chinese (Simplified)_China.utf8")
source("plumber.R", encoding = "UTF-8")
output <- commandArgs(trailingOnly = TRUE)[1]
if (is.na(output)) stop("Pass an existing QA directory")
grey <- function(colour) {
  rgb <- grDevices::col2rgb(colour) / 255
  luminance <- sum(rgb * c(0.2126, 0.7152, 0.0722))
  grDevices::gray(luminance)
}
CHART_COLORS <- vapply(CHART_COLORS, grey, character(1))
NODE_COLORS <- vapply(NODE_COLORS, grey, character(1))
for (key in c("proteomics_volcano", "ppi_network")) {
  fixture <- jsonlite::fromJSON(paste0("../public/r-demo/", key, ".json"), simplifyVector = FALSE)
  plot <- if (key == "proteomics_volcano") make_volcano_plot(fixture$payload) else make_network_plot(fixture$payload)
  grDevices::png(file.path(output, paste0(key, "-grayscale.png")), width = 1650, height = 900, res = 150, type = "cairo")
  print(plot); grDevices::dev.off()
  cat("PASS R grayscale render:", key, "\n")
}
