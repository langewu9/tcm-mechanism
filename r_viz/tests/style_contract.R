# Run from r_viz: Rscript tests/style_contract.R
if (.Platform$OS.type == "windows") Sys.setlocale("LC_CTYPE", "Chinese (Simplified)_China.utf8")
source("plumber.R", encoding = "UTF-8")
stopifnot(RENDERER_VERSION == "r-viz-0.4.3")

counts <- list(title = "合成测试计数", data = list(list(label = "DEMO_A", value = 3), list(label = "DEMO_B", value = 7)))
before <- serialize(counts, NULL)
count_plot <- make_bar_plot(counts)
stopifnot(inherits(count_plot$layers[[1]]$geom, "GeomPoint"), identical(before, serialize(counts, NULL)))
stopifnot(identical(sort(ggplot_build(count_plot)$data[[1]]$x), c(3, 7)))

go <- list(title = "合成富集点图", yLabel = "−log10(FDR)", data = list(
  list(label = "GO:BP · DEMO_BP", value = 3), list(label = "KEGG · DEMO_KEGG", value = 4)))
go_plot <- make_bar_plot(go)
stopifnot(inherits(go_plot$layers[[1]]$geom, "GeomPoint"), nrow(ggplot_build(go_plot)$layout$layout) == 2)

bubble <- list(title = "合成富集气泡", data = list(list(label = "DEMO_TERM", source = "GO:BP", geneRatio = 0.2, adjustedPValue = 0.01, intersectionSize = 4)))
stopifnot(inherits(make_enrichment_bubble_plot(bubble)$scales$get_scales("size"), "ScaleContinuous"))
invalid <- bubble; invalid$data[[1]]$adjustedPValue <- 0
stopifnot(inherits(try(make_enrichment_bubble_plot(invalid), silent = TRUE), "try-error"))

volcano <- list(title = "合成火山图", thresholds = list(log2FoldChange = 1, pValue = 0.05), data = list(
  list(label = "DEMO_UP", log2FoldChange = 2, pValue = 0.001, fdr = 0.01, selected = TRUE),
  list(label = "DEMO_DOWN", log2FoldChange = -2, pValue = 0.001, fdr = 0.01, selected = TRUE),
  list(label = "DEMO_UNSELECTED", log2FoldChange = 3, pValue = 0.001, fdr = 0.01, selected = FALSE)))
before <- serialize(volcano, NULL)
vp <- make_volcano_plot(volcano)
built <- ggplot_build(vp)$data[[1]]
stopifnot(identical(before, serialize(volcano, NULL)))
stopifnot(identical(built$colour, unname(CHART_COLORS[c("up", "down", "neutral")])))
stopifnot(length(unique(built$shape)) == 3, identical(built$x, c(2, -2, 3)))

network <- list(title = "合成网络", layout = "circular", data = list(
  list(id = "a", label = "DEMO_A", type = "protein", degree = 1),
  list(id = "b", label = "DEMO_B", type = "pathway", degree = 1)),
  edges = list(list(source = "a", target = "b", score = 0.9)))
np <- make_network_plot(network)
stopifnot(identical(ggplot_build(np)$data[[2]]$fill, unname(NODE_COLORS[c("protein", "pathway")])))
invalid <- network; invalid$edges[[1]]$target <- "not-present"
stopifnot(inherits(try(make_network_plot(invalid), silent = TRUE), "try-error"))
network$data[[2]]$type <- "unknown"
stopifnot(ggplot_build(make_network_plot(network))$data[[2]]$fill[[2]] == CHART_COLORS[["neutral"]])

wrapped <- wrap_chart_text(paste(rep("长中文标签", 15), collapse = ""))
stopifnot(all(nchar(strsplit(wrapped, "\n")[[1]], type = "width") <= 44))
stopifnot(!any(c("#176b61", "#8cb9ad") %in% c(CHART_COLORS, NODE_COLORS)))
cat("PASS R style: point charts, ontology facets, area-scaled bubbles, up/down shapes, preserved selection, network types, safe unknowns and CJK wrapping\n")

files <- list.files("../public/r-demo", pattern = "\\.json$", full.names = TRUE)
for (file in files[!grepl("manifest\\.json$", files)]) {
  fixture <- jsonlite::fromJSON(file, simplifyVector = FALSE)
  payload <- fixture$payload
  plot <- switch(payload$chartType, bar = make_bar_plot(payload), volcano = make_volcano_plot(payload),
                 network = make_network_plot(payload), enrichment_bubble = make_enrichment_bubble_plot(payload))
  stopifnot(!is.null(plot), length(ggplot_build(plot)$data) > 0)
  cat("PASS fixture profile:", fixture$key, "rows", length(payload$data), "type", payload$chartType, "\n")
}
