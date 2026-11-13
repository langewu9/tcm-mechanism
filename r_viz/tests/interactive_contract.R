if (.Platform$OS.type == "windows") Sys.setlocale("LC_CTYPE", "Chinese (Simplified)_China.utf8")
source("plumber.R", encoding = "UTF-8")
stopifnot(RENDERER_VERSION == "r-viz-0.4.3")
files <- unlist(lapply(c("../public/r-demo", "../public/r-public-demo"), function(directory) list.files(directory, pattern = "\\.json$", full.names = TRUE)))
for (file in files) {
  if (grepl("manifest\\.json$", file)) next
  payload <- jsonlite::fromJSON(file, simplifyVector = FALSE)$payload
  before <- serialize(payload, NULL)
  options <- interactive_options(payload)
  stopifnot(identical(options$textStyle$fontFamily, BROWSER_FONT_FAMILY))
  stopifnot(identical(before, serialize(payload, NULL)))
  actual_points <- sum(vapply(options$series, function(series) length(series$data), integer(1)))
  stopifnot(actual_points == length(payload$data), options$tooltip$renderMode == "richText")
  if (payload$chartType == "network") {
    stopifnot(length(options$series[[1]]$links) == length(payload$edges), options$series[[1]]$emphasis$focus == "adjacency")
    stopifnot(all(vapply(options$series[[1]]$data, function(row) row$originalDegree, numeric(1)) == vapply(payload$data, function(row) row$degree, numeric(1))))
    for (category in options$series[[1]]$categories) stopifnot(category$itemStyle$color == NODE_COLORS[[category$name]])
    stopifnot(all(vapply(options$series[[1]]$links, function(edge) edge$lineStyle$color == "#AEB8C7", logical(1))))
    stopifnot(options$series[[1]]$lineStyle$color != "source")
    stopifnot(options$series[[1]]$layout == "circular", options$series[[1]]$circular$rotateLabel,
      options$series[[1]]$top == 180, options$series[[1]]$bottom == 180,
      options$series[[1]]$lineStyle$curveness == 0.32)
  }
  if (payload$chartType == "volcano") {
    points <- unlist(lapply(options$series, function(series) series$data), recursive = FALSE)
    stopifnot(sum(vapply(points, function(row) row$selected, logical(1))) == sum(vapply(payload$data, function(row) row$selected, logical(1))))
  }
  cat("PASS interactive points preserved:", basename(file), actual_points, "\n")
}
# Internal protein-protein edges must not be silently treated as annotation links.
mixed <- jsonlite::fromJSON("../public/r-demo/gene_pathway_network.json", simplifyVector = FALSE)$payload
stopifnot(is_gene_pathway_network(mixed))
mixed$edges[[length(mixed$edges) + 1L]] <- list(source = "g1", target = "g2", score = 0.5)
stopifnot(!is_gene_pathway_network(mixed))
bad_label <- '</script><script>window.PWNED=true</script><img src=x onerror=alert(1)>'
payload <- list(chartType = "bar", title = bad_label, inputSha256 = paste(rep("a",64),collapse=""), data = list(list(label = bad_label, value = 3)))
html <- make_interactive_html(payload)
stopifnot(!grepl('</script><script>window.PWNED', html, fixed = TRUE))
stopifnot(grepl('connect-src &#39;none&#39;', html, fixed = TRUE), grepl('chart-find', html, fixed = TRUE))
stopifnot(!grepl('<script[^>]+src=', html), !grepl('<link[^>]+href=', html))
json_open <- regexpr('<script type="application/json"[^>]*>', html)
json_close <- tail(gregexpr('</script>', html, fixed = TRUE)[[1]], 1)
json <- substr(html, as.integer(json_open) + attr(json_open,"match.length"), json_close-1)
parsed <- jsonlite::fromJSON(json, simplifyVector = FALSE)
stopifnot(parsed$x$opts$series[[1]]$data[[1]]$label == bad_label)
network_payload <- jsonlite::fromJSON("../public/r-demo/gene_pathway_network.json", simplifyVector = FALSE)$payload
multi_evidence <- list(sourceSlug = "batman", sourceVersion = "v1", sourceRecordId = "row-2",
  relationType = "targets", evidenceType = "database_assertion")
network_payload$edges[[1]]$evidence <- multi_evidence
multi_options <- interactive_options(network_payload)
stopifnot(identical(multi_options$series[[1]]$links[[1]]$evidence, multi_evidence),
  identical(NULL %||% list(), list()), identical("" %||% "fallback", "fallback"),
  identical(c("a", "b") %||% "fallback", c("a", "b")))
network_html <- make_interactive_html(network_payload)
json_open <- regexpr('<script type="application/json"[^>]*>', network_html)
json_close <- tail(gregexpr('</script>', network_html, fixed = TRUE)[[1]], 1)
widget <- jsonlite::fromJSON(substr(network_html, as.integer(json_open) + attr(json_open,"match.length"), json_close-1), simplifyVector = FALSE)
stopifnot(widget$x$defaultLayout == "circular", isTRUE(widget$x$hideIsolatesByDefault),
  length(widget$x$opts$series[[1]]$data) == length(network_payload$data), grepl("圆形布局", network_html, fixed = TRUE))
cat("PASS interactive safety: escaped labels round-trip, no CDN, network-disabled HTML, rich-text tooltips\n")
