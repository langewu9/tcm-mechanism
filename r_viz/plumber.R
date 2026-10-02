library(plumber)
library(ggplot2)
library(svglite)
library(jsonlite)
library(base64enc)

RENDERER_VERSION <- "r-viz-0.1.0"
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
  data$label <- factor(data$label, levels = data$label[order(data$value)])
  ggplot(data, aes(x = label, y = value)) +
    geom_col(fill = "#176b61", width = 0.72) +
    coord_flip() +
    labs(
      title = payload$title,
      x = NULL,
      y = payload$yLabel %||% "数量"
    ) +
    theme_minimal(base_size = 12) +
    theme(
      plot.title = element_text(face = "bold", colour = "#172a28", margin = margin(b = 12)),
      axis.text = element_text(colour = "#344541"),
      panel.grid.major.y = element_blank(),
      panel.grid.minor = element_blank()
    )
}

`%||%` <- function(left, right) if (is.null(left) || !nzchar(as.character(left))) right else left

encode_file <- function(path, format, mime_type, title, svg_data = NULL) {
  if (format == "html") {
    html <- paste0(
      "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
      "<title>", escape_html(title), "</title><style>body{font:16px system-ui,sans-serif;color:#172a28;margin:2rem;background:#f5f7f6}main{max-width:1200px;margin:auto;background:white;padding:2rem;border-radius:16px}img{max-width:100%;height:auto}</style>",
      "<main><h1>", escape_html(title), "</h1><img alt=\"研究结果图表\" src=\"data:image/svg+xml;base64,", svg_data, "\"></main></html>"
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

#* R visualization worker health
#* @get /health
#* @serializer json
function() {
  list(status = "ok", rendererVersion = RENDERER_VERSION)
}

#* Render an approved chart-ready dataset as private artifacts
#* @post /render
#* @serializer json
function(req, res) {
  expected_token <- Sys.getenv("R_VIZ_API_TOKEN", "")
  provided_token <- sub("^Bearer ", "", req$HTTP_AUTHORIZATION %||% "")
  if (!nzchar(expected_token) || !identical(provided_token, expected_token)) {
    res$status <- 401L
    return(list(error = "unauthorized"))
  }
  body <- req$postBody %||% ""
  if (nchar(body, type = "bytes") > MAX_REQUEST_BYTES) {
    res$status <- 413L
    return(list(error = "request_too_large"))
  }
  payload <- tryCatch(jsonlite::fromJSON(body, simplifyVector = FALSE), error = function(error) NULL)
  if (is.null(payload) || !identical(payload$chartType, "bar")) {
    res$status <- 400L
    return(list(error = "invalid_chart_payload"))
  }
  if (is.null(payload$inputSha256) || !grepl("^[a-fA-F0-9]{64}$", payload$inputSha256) ||
      is.null(payload$title) || !is.character(payload$title) || length(payload$title) != 1L ||
      nchar(payload$title, type = "chars") > 200L) {
    res$status <- 400L
    return(list(error = "invalid_chart_metadata"))
  }
  plot <- tryCatch(make_bar_plot(payload), error = function(error) error)
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
  svglite::svglite(svg_path, width = 11, height = 6)
  print(plot)
  grDevices::dev.off()
  grDevices::cairo_pdf(pdf_path, width = 11, height = 6, family = "sans")
  print(plot)
  grDevices::dev.off()
  grDevices::png(png_path, width = 1760, height = 960, res = 160, type = "cairo")
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
      encode_file("", "html", "text/html; charset=utf-8", payload$title, svg_base64)
    )
  )
}
