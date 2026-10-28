# Regenerate only the HTML widgets after an interaction change; preserve static outputs.
if (.Platform$OS.type == "windows") Sys.setlocale("LC_CTYPE", "Chinese (Simplified)_China.utf8")
source("plumber.R", encoding = "UTF-8")
for (directory in c("../public/r-demo", "../public/r-public-demo")) {
  manifest_path <- file.path(directory, "manifest.json")
  manifest <- jsonlite::fromJSON(manifest_path, simplifyVector = FALSE)
  for (i in seq_along(manifest$charts)) {
    key <- manifest$charts[[i]]$key
    fixture <- jsonlite::fromJSON(file.path(directory, paste0(key, ".json")), simplifyVector = FALSE)
    bytes <- charToRaw(enc2utf8(make_interactive_html(fixture$payload)))
    writeBin(bytes, file.path(directory, paste0(key, ".html")))
    manifest$charts[[i]]$artifacts$html <- digest::digest(bytes, algo = "sha256", serialize = FALSE)
    manifest$charts[[i]]$htmlRendererVersion <- RENDERER_VERSION
    cat("PASS refreshed HTML:", key, "\n")
  }
  jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE)
}
