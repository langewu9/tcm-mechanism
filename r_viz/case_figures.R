# Case analysis uses base R stats for clustering and ggplot2 for actual figures.
prepare_case_payload <- function(payload) {
  if (!identical(payload$chartType, "case_cluster")) return(payload)
  rows <- payload$data
  if (!is.list(rows) || length(rows) < 3L || length(rows) > 40L) stop("cluster requires 3–40 herb profiles")
  lengths <- vapply(rows, function(row) length(row$profile), integer(1))
  if (length(unique(lengths)) != 1L || lengths[[1]] < 2L || lengths[[1]] > 10000L) stop("invalid profile dimensions")
  matrix <- do.call(rbind, lapply(rows, function(row) {
    if (!is.character(row$label) || length(row$label) != 1L || nchar(row$label) > 100L) stop("invalid herb name")
    values <- unlist(row$profile)
    if (!is.numeric(values) || any(!is.finite(values)) || any(!values %in% c(0, 1))) stop("invalid binary herb profile")
    values
  }))
  rownames(matrix) <- vapply(rows, function(row) row$label, character(1))
  n_unique <- nrow(unique(matrix))
  if (payload$view == "dendrogram") {
    hc <- stats::hclust(stats::dist(matrix, method = "binary"), method = "average")
    groups <- stats::cutree(hc, k = min(4L, nrow(matrix)))
    positions <- numeric(nrow(matrix)); positions[hc$order] <- seq_len(nrow(matrix))
    nodes <- list(); segments <- list()
    for (i in seq_len(nrow(hc$merge))) {
      children <- lapply(hc$merge[i, ], function(child) {
        if (child < 0) c(x = positions[[-child]], y = 0) else nodes[[child]]
      })
      left <- children[[1]]; right <- children[[2]]; height <- hc$height[[i]]
      segments <- c(segments, list(list(x = left[["x"]], y = left[["y"]], xend = left[["x"]], yend = height),
        list(x = right[["x"]], y = right[["y"]], xend = right[["x"]], yend = height),
        list(x = left[["x"]], y = height, xend = right[["x"]], yend = height)))
      nodes[[i]] <- c(x = mean(c(left[["x"]], right[["x"]])), y = height)
    }
    payload$chartType <- "case_dendrogram"; payload$segments <- segments
    payload$data <- lapply(seq_len(nrow(matrix)), function(i) list(label = rownames(matrix)[[i]], x = positions[[i]], y = 0, value = sum(matrix[i, ]), cluster = groups[[i]]))
    payload$title <- "高频药物层次聚类树状图"
  } else if (payload$view == "elbow") {
    if (n_unique < 3L) stop("not enough distinct profiles for K-Means")
    max_k <- min(8L, n_unique - 1L, nrow(matrix) - 1L)
    payload$chartType <- "case_elbow"
    payload$data <- lapply(seq_len(max_k), function(k) {
      set.seed(42)
      fit <- stats::kmeans(matrix, centers = k, nstart = 25L, iter.max = 100L)
      list(label = paste0("K=", k), x = k, y = fit$tot.withinss, value = fit$tot.withinss)
    })
    payload$title <- "K-Means 肘部图"
  } else if (payload$view == "scatter") {
    k <- payload$k
    if (!is.numeric(k) || length(k) != 1L || k != floor(k) || k < 2L || k >= n_unique || k >= nrow(matrix)) stop("invalid K")
    set.seed(42)
    fit <- stats::kmeans(matrix, centers = k, nstart = 25L, iter.max = 100L)
    pca <- stats::prcomp(matrix, center = TRUE, scale. = FALSE)
    variance <- 100 * pca$sdev^2 / sum(pca$sdev^2)
    payload$chartType <- "case_scatter"; payload$xLabel <- sprintf("PC1 (%.1f%%)", variance[[1]])
    payload$yLabel <- sprintf("PC2 (%.1f%%)", variance[[2]])
    payload$data <- lapply(seq_len(nrow(matrix)), function(i) list(label = rownames(matrix)[[i]], x = pca$x[i, 1], y = pca$x[i, 2], value = sum(matrix[i, ]), cluster = fit$cluster[[i]]))
    payload$title <- paste0("高频药物 K-Means 分组（K=", k, "）")
  } else stop("unsupported case cluster view")
  payload
}

make_case_figure <- function(payload) {
  if (!is.list(payload$data) || !length(payload$data) || length(payload$data) > 625L) stop("invalid case figure rows")
  type <- payload$chartType
  data <- do.call(rbind, lapply(payload$data, function(row) {
    if (!is.character(row$label) || length(row$label) != 1L || nchar(row$label) > 200L) stop("invalid case figure label")
    if (!is.numeric(row$value) || length(row$value) != 1L || !is.finite(row$value)) stop("invalid case figure value")
    if (type != "case_heatmap" && (length(row$x) != 1L || length(row$y) != 1L || !is.numeric(row$x) || !is.numeric(row$y) || !is.finite(row$x) || !is.finite(row$y))) stop("invalid case coordinates")
    if (type == "case_rules" && (!is.numeric(row$lift) || length(row$lift) != 1L || !is.finite(row$lift) || row$lift < 0 || row$x < 0 || row$x > 1 || row$y < 0 || row$y > 1)) stop("invalid association rule")
    data.frame(label = row$label, x = row$x, y = row$y, value = row$value,
      cluster = as.character(row$cluster %||% "1"), lift = row$lift %||% 1)
  }))
  plot <- ggplot(data, aes(x = x, y = y)) + labs(title = payload$title, subtitle = payload$subtitle %||% "") + chart_theme()
  if (type == "case_heatmap") {
    data$x <- factor(data$x, levels = payload$axes); data$y <- factor(data$y, levels = rev(payload$axes))
    plot <- ggplot(data, aes(x = x, y = y, fill = value)) + geom_tile(colour = "white", linewidth = .3) +
      scale_fill_gradient(low = "#FCF6EE", high = "#9C2B22", name = "共现数") +
      labs(title = payload$title, subtitle = payload$subtitle, x = NULL, y = NULL) + chart_theme() +
      theme(axis.text.x = element_text(angle = 50, hjust = 1), panel.grid = element_blank())
  } else if (type == "case_dendrogram") {
    segments <- do.call(rbind, lapply(payload$segments, as.data.frame))
    plot <- plot + geom_segment(data = segments, aes(x = x, y = y, xend = xend, yend = yend), inherit.aes = FALSE, colour = "#776650", linewidth = .5) +
      geom_point(aes(colour = cluster), size = 2) +
      scale_x_continuous(breaks = data$x, labels = data$label) + labs(x = NULL, y = "Jaccard 距离", colour = "分组") +
      theme(axis.text.x = element_text(angle = 65, hjust = 1), panel.grid.major.x = element_blank())
  } else if (type == "case_scatter") {
    plot <- plot + geom_point(aes(colour = cluster, size = value), alpha = .9) +
      ggrepel::geom_text_repel(aes(label = label, colour = cluster), family = PLOT_FONT_FAMILY, size = 3.5, seed = 42, max.overlaps = Inf) +
      labs(x = payload$xLabel, y = payload$yLabel, colour = "分组", size = "频次")
  } else if (type == "case_elbow") {
    plot <- plot + geom_line(colour = "#9C2B22", linewidth = .7) + geom_point(colour = "#9C2B22", size = 3) +
      scale_x_continuous(breaks = data$x) + labs(x = "聚类数 K", y = "簇内平方和 (WSS)")
  } else if (type == "case_rules") {
    plot <- plot + geom_point(aes(size = value, colour = lift), alpha = .8) +
      scale_colour_gradient(low = "#C6A87C", high = "#9C2B22", name = "提升度") +
      labs(x = "支持度", y = "置信度", size = "共现数")
  } else stop("unsupported case figure")
  plot
}

case_interactive_options <- function(payload, options) {
  type <- payload$chartType
  options$grid <- list(left = 90, right = 80, top = 50, bottom = if (type == "case_dendrogram") 135 else 90, containLabel = TRUE)
  options$xAxis <- list(type = "value", name = payload$xLabel %||% "", nameLocation = "middle", nameGap = 32)
  options$yAxis <- list(type = "value", name = payload$yLabel %||% "", nameLocation = "middle", nameGap = 45)
  options$dataZoom <- list(list(type = "inside", xAxisIndex = 0), list(type = "slider", xAxisIndex = 0, bottom = 8))
  points <- lapply(payload$data, function(row) list(name = row$label, label = row$label, cluster = row$cluster %||% NULL,
    lift = row$lift %||% NULL, count = row$value, value = c(row$x, row$y)))
  if (type == "case_heatmap") {
    options$xAxis <- list(type = "category", data = payload$axes, axisLabel = list(rotate = 45, interval = 0))
    options$yAxis <- list(type = "category", data = rev(payload$axes), axisLabel = list(interval = 0))
    options$visualMap <- list(min = 0, max = max(vapply(payload$data, function(row) row$value, numeric(1))), calculable = TRUE, orient = "vertical", right = 0, top = "center", inRange = list(color = c("#FCF6EE", "#C6A87C", "#9C2B22")))
    options$series <- list(list(type = "heatmap", data = lapply(payload$data, function(row) list(name = row$label, label = row$label, count = row$value, value = c(match(row$x, payload$axes)-1, match(row$y, rev(payload$axes))-1, row$value)))))
  } else if (type == "case_dendrogram") {
    ordered <- payload$data[order(vapply(payload$data, function(row) row$x, numeric(1)))]
    options$xAxis <- list(type = "value", min = 0, max = length(ordered)+1, axisLabel = list(show = FALSE), splitLine = list(show = FALSE))
    options$yAxis$name <- "Jaccard 距离"
    lines <- lapply(payload$segments, function(segment) list(type = "line", symbol = "none", silent = TRUE, lineStyle = list(color = "#776650", width = 1.2), data = list(c(segment$x, segment$y), c(segment$xend, segment$yend))))
    options$series <- c(list(list(type = "scatter", data = points, symbolSize = 8, label = list(show = TRUE, position = "bottom", rotate = 65, fontSize = 12, formatter = htmlwidgets::JS("function(p){return p.data.label;}")))), lines)
  } else if (type == "case_elbow") {
    options$xAxis$name <- "K"; options$xAxis$minInterval <- 1; options$yAxis$name <- "簇内平方和 (WSS)"
    options$series <- list(list(type = "line", data = points, symbolSize = 10, lineStyle = list(color = "#9C2B22")))
  } else if (type == "case_scatter") {
    groups <- sort(unique(vapply(payload$data, function(row) as.character(row$cluster), character(1))))
    options$legend <- list(top = 5, data = paste0("组 ", groups))
    options$series <- lapply(groups, function(group) list(name = paste0("组 ", group), type = "scatter", symbolSize = 15,
      data = Filter(function(row) as.character(row$cluster) == group, points), label = list(show = TRUE, position = "top", formatter = htmlwidgets::JS("function(p){return p.data.label;}"))))
  } else if (type == "case_rules") {
    options$xAxis$name <- "支持度"; options$yAxis$name <- "置信度"
    points <- lapply(points, function(row) { row$value <- c(row$value, row$lift); row })
    lifts <- vapply(payload$data, function(row) row$lift, numeric(1))
    options$visualMap <- list(min = min(lifts), max = max(lifts), dimension = 2, orient = "vertical", right = 0, top = "center", text = c("提升度", ""), inRange = list(color = c("#C6A87C", "#9C2B22")))
    options$series <- list(list(type = "scatter", data = points, symbolSize = htmlwidgets::JS("function(v,p){return 7+Math.sqrt(p.data.count);}")))
  }
  options$tooltip$formatter <- htmlwidgets::JS("function(p){var d=p.data;return d.label+(d.cluster?'\\n分组: '+d.cluster:'')+'\\n数值: '+d.count+(d.lift?'\\n提升度: '+d.lift.toFixed(3):'');}")
  options
}
