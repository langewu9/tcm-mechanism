library(plumber)
library(ggplot2)
library(svglite)
library(jsonlite)
library(base64enc)

RENDERER_VERSION <- "r-viz-0.2.0"
PLOT_FONT_FAMILY <- Sys.getenv(
  "R_VIZ_FONT_FAMILY",
  if (.Platform$OS.type == "windows") "Microsoft YaHei" else "Noto Sans CJK SC"
)
MAX_REQUEST_BYTES <- 1024L * 1024L
MAX_DATA_POINTS <- 100L

escape_html <- function(value) {
  value <- gsub("&", "&amp;", as.character(value), fixed = TRUE)
  value <- gsub("<", "&lt;", value, fixed = TRUE)
  value <- gsub(">", "&gt;", value, fixed = TRUE)
  value <- gsub('"', "&quot;", value, fixed = TRUE)
  gsub("'", "&#39;", value, fixed = TRUE)
}

make_bar_plot <- function(payload) {
  if (is.null(payload$data) || !is.list(payload$data) || length(payload$data) < 1L || length(payload$data) > MAX_DATA_POINTS) {
    stop("data must contain between 1 and 100 points", call. = FALSE)
  }
  labels <- vapply(payload$data, function(item) {
    label <- item$label
    if (!is.character(label) || length(label) != 1L || !nzchar(trimws(label)) || nchar(label, type = "chars") > 120L) {
      stop("every data point needs a label of at most 120 characters", call. = FALSE)
    }
    label
  }, character(1))
  values <- vapply(payload$data, function(item) {
    value <- item$value
    if (!is.numeric(value) || length(value) != 1L || !is.finite(value)) {
      stop("every data point needs a finite numeric value", call. = FALSE)
    }
    value
  }, numeric(1))
  data <- data.frame(label = labels, value = values, stringsAsFactors = FALSE)
  data$label <- factor(data$label, levels = unique(data$label[order(data$value)]))
  ggplot(data, aes(x = label, y = value)) +
    geom_col(fill = "#176b61", width = 0.72) +
    coord_flip() +
    labs(
      title = payload$title,
      subtitle = payload$subtitle %||% "",
      x = NULL,
      y = payload$yLabel %||% "数量"
    ) +
    theme_minimal(base_size = 12, base_family = PLOT_FONT_FAMILY) +
    theme(
      plot.title = element_text(face = "bold", colour = "#172a28", margin = margin(b = 12)),
      axis.text = element_text(colour = "#344541"),
      panel.grid.major.y = element_blank(),
      panel.grid.minor = element_blank()
    )
}

make_enrichment_bubble_plot <- function(payload) {
  allowed_sources <- c("GO:BP", "GO:CC", "GO:MF", "KEGG", "Reactome")
  if (is.null(payload$data) || !is.list(payload$data) || length(payload$data) < 1L || length(payload$data) > MAX_DATA_POINTS) {
    stop("data must contain between 1 and 100 enrichment terms", call. = FALSE)
  }
  terms <- lapply(payload$data, function(item) {
    label <- item$label
    source <- item$source
    ratio <- item$geneRatio
    fdr <- item$adjustedPValue
    intersection <- item$intersectionSize
    if (!is.character(label) || length(label) != 1L || !nzchar(trimws(label)) || nchar(label, type = "chars") > 140L) {
      stop("every enrichment term needs a label of at most 140 characters", call. = FALSE)
    }
    if (!is.character(source) || length(source) != 1L || !(source %in% allowed_sources)) {
      stop("every enrichment term needs an approved source", call. = FALSE)
    }
    if (!is.numeric(ratio) || length(ratio) != 1L || !is.finite(ratio) || ratio < 0 || ratio > 1) {
      stop("geneRatio must be a finite number between 0 and 1", call. = FALSE)
    }
    if (!is.numeric(fdr) || length(fdr) != 1L || !is.finite(fdr) || fdr <= 0 || fdr > 0.05) {
      stop("adjustedPValue must be an FDR value greater than 0 and at most 0.05", call. = FALSE)
    }
    if (!is.numeric(intersection) || length(intersection) != 1L || !is.finite(intersection) || intersection < 1 || intersection != floor(intersection)) {
      stop("intersectionSize must be a positive integer", call. = FALSE)
    }
    data.frame(
      label = label,
      source = source,
      geneRatio = ratio,
      adjustedPValue = fdr,
      intersectionSize = intersection,
      stringsAsFactors = FALSE
    )
  })
  data <- do.call(rbind, terms)
  data$source <- factor(data$source, levels = allowed_sources)
  ggplot(data, aes(x = geneRatio, y = reorder(label, geneRatio))) +
    geom_point(aes(size = intersectionSize, colour = -log10(adjustedPValue)), alpha = 0.85) +
    facet_grid(source ~ ., scales = "free_y", space = "free_y", drop = TRUE) +
    scale_size_continuous(range = c(3, 10), name = payload$sizeLabel %||% "命中基因数") +
    scale_colour_gradient(low = "#8cb9ad", high = "#a33b36", name = payload$colorLabel %||% "−log10(FDR)") +
    labs(title = payload$title, subtitle = payload$subtitle %||% "", x = payload$xLabel %||% "GeneRatio", y = NULL) +
    theme_minimal(base_size = 12, base_family = PLOT_FONT_FAMILY) +
    theme(
      plot.title = element_text(face = "bold", colour = "#172a28", margin = margin(b = 12)),
      plot.subtitle = element_text(colour = "#53635f", margin = margin(b = 10)),
      axis.text = element_text(colour = "#344541"),
      panel.grid.minor = element_blank(),
      strip.text.y = element_text(angle = 0, face = "bold", colour = "#176b61"),
      panel.spacing.y = grid::unit(0.7, "lines")
    )
}

make_volcano_plot <- function(payload) {
  if (is.null(payload$data) || !is.list(payload$data) || length(payload$data) < 1L || length(payload$data) > 5000L) {
    stop("data must contain between 1 and 5000 volcano points", call. = FALSE)
  }
  thresholds <- payload$thresholds
  if (!is.list(thresholds) || !is.numeric(thresholds$log2FoldChange) || length(thresholds$log2FoldChange) != 1L ||
      !is.finite(thresholds$log2FoldChange) || thresholds$log2FoldChange < 0 ||
      !is.numeric(thresholds$pValue) || length(thresholds$pValue) != 1L ||
      !is.finite(thresholds$pValue) || thresholds$pValue <= 0 || thresholds$pValue > 1) {
    stop("volcano thresholds are invalid", call. = FALSE)
  }
  points <- lapply(payload$data, function(item) {
    label <- item$label
    fold_change <- item$log2FoldChange
    p_value <- item$pValue
    fdr <- item$fdr
    selected <- item$selected
    if (!is.character(label) || length(label) != 1L || !nzchar(trimws(label)) || nchar(label, type = "chars") > 120L) {
      stop("every volcano point needs a label of at most 120 characters", call. = FALSE)
    }
    if (!is.numeric(fold_change) || length(fold_change) != 1L || !is.finite(fold_change)) {
      stop("log2FoldChange must be finite", call. = FALSE)
    }
    if (!is.numeric(p_value) || length(p_value) != 1L || !is.finite(p_value) || p_value < 0 || p_value > 1) {
      stop("pValue must be between 0 and 1", call. = FALSE)
    }
    if (!is.null(fdr) && (!is.numeric(fdr) || length(fdr) != 1L || !is.finite(fdr) || fdr < 0 || fdr > 1)) {
      stop("fdr must be null or a finite number between 0 and 1", call. = FALSE)
    }
    if (!is.logical(selected) || length(selected) != 1L || is.na(selected)) {
      stop("selected must be a boolean", call. = FALSE)
    }
    data.frame(
      label = label,
      log2FoldChange = fold_change,
      pValue = p_value,
      fdr = if (is.null(fdr)) NA_real_ else fdr,
      selected = selected,
      stringsAsFactors = FALSE
    )
  })
  data <- do.call(rbind, points)
  data$negLog10P <- -log10(pmax(data$pValue, .Machine$double.xmin))
  data$selected <- factor(data$selected, levels = c(FALSE, TRUE), labels = c("未通过筛选", "通过筛选"))
  ggplot(data, aes(x = log2FoldChange, y = negLog10P)) +
    geom_point(aes(colour = selected), alpha = 0.7, size = 1.6) +
    geom_vline(xintercept = c(-thresholds$log2FoldChange, thresholds$log2FoldChange),
               linetype = "dashed", colour = "#75827e", linewidth = 0.45) +
    geom_hline(yintercept = -log10(thresholds$pValue),
               linetype = "dashed", colour = "#75827e", linewidth = 0.45) +
    scale_colour_manual(values = c("未通过筛选" = "#9aa7a3", "通过筛选" = "#b34d43"), drop = FALSE) +
    labs(
      title = payload$title,
      subtitle = payload$subtitle %||% "",
      x = payload$xLabel %||% "log2 Fold Change",
      y = payload$yLabel %||% "−log10(P 值)",
      colour = "阈值筛选"
    ) +
    theme_minimal(base_size = 12, base_family = PLOT_FONT_FAMILY) +
    theme(
      plot.title = element_text(face = "bold", colour = "#172a28", margin = margin(b = 10)),
      plot.subtitle = element_text(colour = "#53635f", margin = margin(b = 10)),
      axis.text = element_text(colour = "#344541"),
      panel.grid.minor = element_blank(),
      legend.position = "top"
    )
}

make_network_plot <- function(payload) {
  if (!is.list(payload$data) || length(payload$data) < 2L || length(payload$data) > 80L ||
      !is.list(payload$edges) || length(payload$edges) < 1L || length(payload$edges) > 500L ||
      !(payload$layout %in% c("circular", "layered"))) {
    stop("network must contain 2–80 nodes and 1–500 edges with a supported layout", call. = FALSE)
  }
  nodes <- lapply(payload$data, function(item) {
    if (!is.character(item$id) || length(item$id) != 1L || !nzchar(item$id) || nchar(item$id) > 200L ||
        !is.character(item$label) || length(item$label) != 1L || !nzchar(item$label) || nchar(item$label) > 120L ||
        !is.character(item$type) || length(item$type) != 1L || nchar(item$type) > 40L ||
        !is.numeric(item$degree) || length(item$degree) != 1L || !is.finite(item$degree) || item$degree < 0) {
      stop("invalid network node", call. = FALSE)
    }
    data.frame(id = item$id, label = item$label, type = item$type, degree = item$degree)
  })
  nodes <- do.call(rbind, nodes)
  if (anyDuplicated(nodes$id)) stop("duplicate network node ids", call. = FALSE)
  if (identical(payload$layout, "circular")) {
    angles <- 2 * pi * (seq_len(nrow(nodes)) - 1) / nrow(nodes)
    nodes$x <- cos(angles)
    nodes$y <- sin(angles)
  } else {
    preferred <- c("herb", "ingredient", "compound", "gene", "protein", "target", "pathway", "disease")
    types <- c(intersect(preferred, unique(nodes$type)), setdiff(unique(nodes$type), preferred))
    nodes$x <- match(nodes$type, types)
    nodes$y <- ave(seq_len(nrow(nodes)), nodes$type, FUN = function(group) seq(-1, 1, length.out = length(group)))
  }
  edges <- lapply(payload$edges, function(item) {
    if (!is.character(item$source) || length(item$source) != 1L ||
        !is.character(item$target) || length(item$target) != 1L || item$source == item$target ||
        !(item$source %in% nodes$id) || !(item$target %in% nodes$id) ||
        !is.numeric(item$score) || length(item$score) != 1L || !is.finite(item$score) || item$score < 0 || item$score > 1) {
      stop("invalid network edge or endpoint", call. = FALSE)
    }
    left <- nodes[match(item$source, nodes$id), ]
    right <- nodes[match(item$target, nodes$id), ]
    data.frame(x = left$x, y = left$y, xend = right$x, yend = right$y, score = item$score)
  })
  edges <- do.call(rbind, edges)
  labels <- nodes[order(-nodes$degree, nodes$id), ]
  if (nrow(labels) > 40L) labels <- head(labels, 20L)
  ggplot() +
    geom_segment(data = edges, aes(x = x, y = y, xend = xend, yend = yend, linewidth = score), colour = "#889692", alpha = 0.45) +
    geom_point(data = nodes, aes(x = x, y = y, size = degree, colour = type)) +
    geom_text(data = labels, aes(x = x, y = y, label = label), family = PLOT_FONT_FAMILY, size = 3, vjust = -1.3, check_overlap = TRUE) +
    scale_size_continuous(range = c(3, 9)) + scale_linewidth_continuous(range = c(0.25, 1.1), guide = "none") +
    labs(title = payload$title, subtitle = payload$subtitle %||% "", size = "子图 degree", colour = "节点类型") +
    coord_cartesian(clip = "off") + theme_void(base_size = 11, base_family = PLOT_FONT_FAMILY) +
    theme(legend.position = "bottom", plot.margin = margin(20, 40, 20, 40), plot.title = element_text(face = "bold"))
}

`%||%` <- function(left, right) if (is.null(left) || !nzchar(as.character(left))) right else left

encode_file <- function(path, format, mime_type, title, svg_data = NULL, chart_payload = NULL) {
  if (format == "html") {
    html <- paste0(
      "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
      "<title>", escape_html(title), "</title><style>body{font:16px system-ui,sans-serif;color:#172a28;margin:2rem;background:#f5f7f6}main{max-width:1200px;margin:auto;background:white;padding:2rem;border-radius:16px}img{max-width:100%;height:auto}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;margin-top:1rem}th,td{border:1px solid #dce4e1;padding:.55rem .7rem;text-align:left}th{background:#eef4f1}</style>",
      "<main><h1>", escape_html(title), "</h1><img alt=\"研究结果图表\" src=\"data:image/svg+xml;base64,", svg_data, "\">",
      make_data_table_html(chart_payload), "</main></html>"
    )
    bytes <- charToRaw(enc2utf8(html))
  } else {
    size <- file.info(path)$size
    bytes <- readBin(path, what = "raw", n = size)
  }
  list(
    format = format,
    mimeType = mime_type,
    filename = paste0("chart.", format),
    bytesBase64 = base64enc::base64encode(bytes)
  )
}

make_data_table_html <- function(payload) {
  if (identical(payload$chartType, "network")) {
    headers <- c("节点 ID", "节点名称", "类型", "展示子图 degree")
    rows <- lapply(payload$data, function(item) c(item$id, item$label, item$type, as.character(item$degree)))
    node_header <- paste0("<th>", vapply(headers, escape_html, character(1)), "</th>", collapse = "")
    node_rows <- vapply(rows, function(row) paste0("<tr><td>", paste(vapply(row, escape_html, character(1)), collapse = "</td><td>"), "</td></tr>"), character(1))
    edge_rows <- vapply(payload$edges, function(edge) paste0("<tr><td>", escape_html(edge$source), "</td><td>", escape_html(edge$target), "</td><td>", escape_html(format(edge$score, digits = 4)), "</td></tr>"), character(1))
    return(paste0("<section><h2>节点</h2><div class=\"table-wrap\"><table><thead><tr>", node_header, "</tr></thead><tbody>", paste(node_rows, collapse = ""), "</tbody></table></div><h2>实际展示关系</h2><div class=\"table-wrap\"><table><thead><tr><th>起点</th><th>终点</th><th>互作评分 / 本地关系存在标记</th></tr></thead><tbody>", paste(edge_rows, collapse = ""), "</tbody></table></div></section>"))
  } else if (identical(payload$chartType, "enrichment_bubble")) {
    headers <- c("来源", "功能条目", "GeneRatio", "FDR", "命中基因数")
    rows <- lapply(payload$data, function(item) {
      c(item$source, item$label, format(item$geneRatio, digits = 5, trim = TRUE),
        format(item$adjustedPValue, digits = 5, trim = TRUE), as.character(item$intersectionSize))
    })
  } else if (identical(payload$chartType, "volcano")) {
    headers <- c("基因/蛋白", "log2FC", "P 值", "FDR", "阈值筛选")
    format_value <- function(value) {
      if (is.null(value) || !is.numeric(value) || length(value) != 1L || !is.finite(value)) "—"
      else format(value, digits = 6, trim = TRUE)
    }
    rows <- lapply(payload$data, function(item) {
      c(item$label, format_value(item$log2FoldChange), format_value(item$pValue),
        format_value(item$fdr), if (isTRUE(item$selected)) "通过" else "未通过")
    })
  } else {
    headers <- c("条目", "数值")
    rows <- lapply(payload$data, function(item) c(item$label, format(item$value, digits = 6, trim = TRUE)))
  }
  header_html <- paste0("<th>", vapply(headers, escape_html, character(1)), "</th>", collapse = "")
  row_html <- vapply(rows, function(row) {
    cells <- paste0("<td>", vapply(row, escape_html, character(1)), "</td>", collapse = "")
    paste0("<tr>", cells, "</tr>")
  }, character(1))
  paste0(
    "<section><h2>图表对应数据</h2><div class=\"table-wrap\"><table><thead><tr>", header_html,
    "</tr></thead><tbody>", paste(row_html, collapse = ""), "</tbody></table></div></section>"
  )
}

#* R visualization worker health
#* @get /health
#* @serializer unboxedJSON
function() {
  list(status = "ok", rendererVersion = RENDERER_VERSION)
}

#* Render an approved chart-ready dataset as private artifacts
#* @post /render
#* @serializer unboxedJSON
function(req, res) {
  expected_token <- Sys.getenv("R_VIZ_API_TOKEN", "")
  provided_token <- sub("^Bearer ", "", req$HTTP_AUTHORIZATION %||% "")
  if (!nzchar(expected_token) || !identical(provided_token, expected_token)) {
    res$status <- 401L
    return(list(error = "unauthorized"))
  }
  body <- req$postBody %||% ""
  # HTTP JSON is UTF-8, including on Windows with a non-UTF-8 native locale.
  Encoding(body) <- "UTF-8"
  if (nchar(body, type = "bytes") > MAX_REQUEST_BYTES) {
    res$status <- 413L
    return(list(error = "request_too_large"))
  }
  payload <- tryCatch(jsonlite::fromJSON(body, simplifyVector = FALSE), error = function(error) NULL)
  if (is.null(payload) || !is.list(payload) || !is.character(payload$chartType) ||
      length(payload$chartType) != 1L || !(payload$chartType %in% c("bar", "enrichment_bubble", "volcano", "network"))) {
    res$status <- 400L
    return(list(error = "invalid_chart_payload"))
  }
  if (is.null(payload$inputSha256) || !grepl("^[a-fA-F0-9]{64}$", payload$inputSha256) ||
      is.null(payload$title) || !is.character(payload$title) || length(payload$title) != 1L ||
      nchar(payload$title, type = "chars") > 200L) {
    res$status <- 400L
    return(list(error = "invalid_chart_metadata"))
  }
  if (!is.null(payload$subtitle) && (!is.character(payload$subtitle) || length(payload$subtitle) != 1L || nchar(payload$subtitle, type = "chars") > 280L)) {
    res$status <- 400L
    return(list(error = "invalid_chart_subtitle"))
  }
  plot <- tryCatch(
    if (identical(payload$chartType, "network")) make_network_plot(payload) else if (identical(payload$chartType, "bar")) make_bar_plot(payload) else if (identical(payload$chartType, "volcano")) make_volcano_plot(payload) else make_enrichment_bubble_plot(payload),
    error = function(error) error
  )
  if (inherits(plot, "error")) {
    res$status <- 400L
    return(list(error = "invalid_chart_data", message = conditionMessage(plot)))
  }

  temporary_directory <- tempfile("r-viz-")
  dir.create(temporary_directory, mode = "0700")
  on.exit(unlink(temporary_directory, recursive = TRUE), add = TRUE)
  svg_path <- file.path(temporary_directory, "chart.svg")
  pdf_path <- file.path(temporary_directory, "chart.pdf")
  png_path <- file.path(temporary_directory, "chart.png")
  chart_height <- if (identical(payload$chartType, "enrichment_bubble")) min(16, max(6, 2 + 0.22 * length(payload$data))) else 6
  svglite::svglite(svg_path, width = 11, height = chart_height)
  print(plot)
  grDevices::dev.off()
  grDevices::cairo_pdf(pdf_path, width = 11, height = chart_height, family = PLOT_FONT_FAMILY)
  print(plot)
  grDevices::dev.off()
  grDevices::png(png_path, width = 1760, height = round(160 * chart_height), res = 160, type = "cairo")
  print(plot)
  grDevices::dev.off()

  svg_bytes <- readBin(svg_path, what = "raw", n = file.info(svg_path)$size)
  svg_base64 <- base64enc::base64encode(svg_bytes)
  list(
    rendererVersion = RENDERER_VERSION,
    inputSha256 = payload$inputSha256,
    artifacts = list(
      encode_file(svg_path, "svg", "image/svg+xml", payload$title),
      encode_file(pdf_path, "pdf", "application/pdf", payload$title),
      encode_file(png_path, "png", "image/png", payload$title),
      encode_file("", "html", "text/html; charset=utf-8", payload$title, svg_base64, payload)
    )
  )
}
