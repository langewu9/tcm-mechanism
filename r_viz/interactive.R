# R-generated echarts4r widgets. Dependencies are inlined: no CDN or telemetry.
is_gene_pathway_network <- function(payload) {
  if (payload$chartType != "network") return(FALSE)
  types <- unique(vapply(payload$data, function(row) row$type, character(1)))
  if (length(types) != 2L || !"pathway" %in% types || !any(types %in% c("gene", "protein", "target"))) return(FALSE)
  node_types <- setNames(vapply(payload$data, function(row) row$type, character(1)), vapply(payload$data, function(row) row$id, character(1)))
  # Annotation-only graphs can fold isolated nodes without changing the source data.
  all(vapply(payload$edges, function(edge) xor(node_types[[edge$source]] == "pathway", node_types[[edge$target]] == "pathway"), logical(1)))
}

interactive_options <- function(payload) {
  options <- list(animation = FALSE, backgroundColor = "#FFFFFF",
    color = unname(CHART_COLORS[c("down", "up", "purple", "neutral")]),
    textStyle = list(fontFamily = BROWSER_FONT_FAMILY, fontSize = 14, color = CHART_COLORS[["ink"]]),
    aria = list(enabled = TRUE), tooltip = list(trigger = "item", renderMode = "richText", confine = TRUE),
    toolbox = list(right = 12, feature = list(restore = list(title = "还原视图"), saveAsImage = list(title = "导出当前视图", type = "png", pixelRatio = 3))))
  if (payload$chartType == "network") {
    types <- unique(vapply(payload$data, function(row) row$type, character(1)))
    bipartite <- is_gene_pathway_network(payload)
    type_color <- function(type) if (type %in% names(NODE_COLORS)) NODE_COLORS[[type]] else CHART_COLORS[["neutral"]]
    type_symbol <- function(type) switch(type, herb = "rect", formula = "rect", compound = "triangle", ingredient = "triangle", pathway = "diamond", disease = "roundRect", syndrome = "roundRect", "circle")
    nodes <- lapply(payload$data, function(row) {
      list(id = row$id, name = row$id, label = row$label, displayLabel = row$label, value = row$degree, originalDegree = row$degree,
        nodeType = row$type, category = match(row$type, types) - 1L,
        symbol = type_symbol(row$type),
        symbolSize = 9 + 3 * sqrt(row$degree), itemStyle = list(color = type_color(row$type), borderColor = "white", borderWidth = 1.5))
    })
    links <- lapply(payload$edges, function(row) list(source = row$source, target = row$target, value = row$score, score = row$score, evidence = row$evidence %||% list(),
      lineStyle = list(color = "#AEB8C7", width = 0.6 + 0.5 * row$score, opacity = 0.45, curveness = 0.32)))
    options$legend <- list(type = "scroll", top = 8, data = lapply(types, function(type) list(name = type, icon = type_symbol(type))),
      formatter = htmlwidgets::JS("function(name){return ({protein:'蛋白 / 基因',gene:'基因',target:'靶点',pathway:'通路',herb:'中药',ingredient:'成分',compound:'化合物',disease:'疾病',formula:'方剂',syndrome:'证候'})[name]||name;}"))
    options$title <- list(text = "Circular network · 节点大小表示当前连接度", left = "center", bottom = 10,
      textStyle = list(fontSize = 14, fontWeight = "normal", color = CHART_COLORS[["muted"]]))
    options$series <- list(list(name = "关系网络", type = "graph", layout = "circular", roam = TRUE, draggable = TRUE,
      top = 180, bottom = 180, left = 170, right = 170, scaleLimit = list(min = 0.25, max = 8),
      circular = list(rotateLabel = TRUE), force = list(repulsion = 240, edgeLength = c(50, 120), gravity = 0.06),
      categories = lapply(types, function(type) list(name = type, itemStyle = list(color = type_color(type)))), data = nodes, links = links,
      label = list(show = TRUE, position = "right", fontSize = 12, width = 140, overflow = "truncate", distance = 8, color = CHART_COLORS[["ink"]],
        formatter = htmlwidgets::JS("function(p){return p.data.displayLabel||p.data.label;}")),
      emphasis = list(focus = "adjacency", lineStyle = list(color = "#4E6D9C", opacity = 0.9, width = 1.8), label = list(show = TRUE)),
      blur = list(itemStyle = list(opacity = 0.08), lineStyle = list(opacity = 0.025)),
      lineStyle = list(color = "#AEB8C7", curveness = 0.32)))
    options$tooltip$formatter <- htmlwidgets::JS("function(p){if(p.dataType==='edge'){return p.data.source+' → '+p.data.target+'\\n评分 / 关系标记: '+p.data.score;}return p.data.displayLabel+'\\n类型: '+p.data.nodeType+'\\n展示子图连接度: '+p.data.value+'\\n原始输入连接度: '+p.data.originalDegree;}")
  } else {
    options$grid <- list(left = 85, right = 70, top = 65, bottom = 95, containLabel = TRUE)
    options$dataZoom <- list(list(type = "inside", xAxisIndex = 0), list(type = "slider", xAxisIndex = 0, bottom = 20))
    options$xAxis <- list(type = "value", nameLocation = "middle", nameGap = 35, splitLine = list(lineStyle = list(color = CHART_COLORS[["grid"]])))
    options$yAxis <- list(type = "value", nameLocation = "middle", nameGap = 50, splitLine = list(lineStyle = list(color = CHART_COLORS[["grid"]])))
    if (payload$chartType == "volcano") {
      rows <- lapply(payload$data, function(row) {
        direction <- if (!isTRUE(row$selected)) "未通过" else if (row$log2FoldChange > 0) "上调" else if (row$log2FoldChange < 0) "下调" else "通过筛选"
        list(name = row$label, label = row$label, value = c(row$log2FoldChange, -log10(max(row$pValue, 1e-300))),
          pValue = row$pValue, fdr = row$fdr, selected = row$selected, direction = direction)
      })
      groups <- c("未通过", "上调", "下调", "通过筛选")
      colors <- unname(CHART_COLORS[c("neutral", "up", "down", "purple")])
      options$legend <- list(top = 5, data = groups)
      options$xAxis$name <- "log2 Fold Change"
      options$yAxis$name <- "−log10(P 值)"
      options$brush <- list(toolbox = c("rect", "polygon", "clear"), xAxisIndex = 0, yAxisIndex = 0, brushMode = "single")
      options$series <- lapply(seq_along(groups), function(i) list(name = groups[i], type = "scatter", symbol = c("circle", "triangle", "diamond", "rect")[[i]],
        symbolSize = 7, itemStyle = list(color = colors[[i]], opacity = 0.8), emphasis = list(scale = 1.7),
        data = Filter(function(row) row$direction == groups[[i]], rows)))
      options$series[[1]]$markLine <- list(silent = TRUE, symbol = "none", lineStyle = list(color = CHART_COLORS[["muted"]], type = "dashed"),
        data = list(list(xAxis = payload$thresholds$log2FoldChange), list(xAxis = -payload$thresholds$log2FoldChange), list(yAxis = -log10(payload$thresholds$pValue))))
      options$tooltip$formatter <- htmlwidgets::JS("function(p){var d=p.data;return d.label+'\\nlog2FC: '+d.value[0]+'\\nP: '+d.pValue+'\\nFDR: '+(d.fdr==null?'未提供':d.fdr)+'\\n保存的筛选状态: '+(d.selected?'通过':'未通过');}")
    } else if (payload$chartType == "enrichment_bubble") {
      labels <- vapply(payload$data, function(row) row$label, character(1))
      options$yAxis <- list(type = "category", data = labels, inverse = TRUE, axisLabel = list(width = 250, overflow = "truncate", fontSize = 13))
      options$xAxis$name <- payload$xLabel %||% "GeneRatio"
      sources <- unique(vapply(payload$data, function(row) row$source, character(1)))
      options$legend <- list(top = 5, data = sources)
      options$visualMap <- list(type = "continuous", min = min(vapply(payload$data, function(row) -log10(row$adjustedPValue), numeric(1))),
        max = max(vapply(payload$data, function(row) -log10(row$adjustedPValue), numeric(1))), dimension = 2, orient = "vertical", right = 2, top = "center",
        text = c("−log10 FDR", ""), calculable = TRUE, inRange = list(color = c("#B9ACCF", "#70578B", "#493359")))
      options$series <- lapply(sources, function(source) list(name = source, type = "scatter",
        symbolSize = htmlwidgets::JS("function(v){return 7+3*Math.sqrt(v[3]);}"),
        data = lapply(which(vapply(payload$data, function(row) row$source == source, logical(1))), function(i) {
          row <- payload$data[[i]]; list(name = row$label, label = row$label, source = row$source, fdr = row$adjustedPValue,
            value = c(row$geneRatio, i - 1L, -log10(row$adjustedPValue), row$intersectionSize))
        })))
      options$dataZoom[[1]] <- list(type = "inside", yAxisIndex = 0)
      options$dataZoom[[2]] <- list(type = "slider", yAxisIndex = 0, right = 45, width = 12)
      options$tooltip$formatter <- htmlwidgets::JS("function(p){var d=p.data;return d.label+'\\n来源: '+d.source+'\\nGeneRatio: '+d.value[0]+'\\n命中数: '+d.value[3]+'\\nFDR: '+d.fdr;}")
    } else {
      options$xAxis$name <- payload$yLabel %||% "数值"
      options$yAxis <- list(type = "category", data = vapply(payload$data, function(row) row$label, character(1)), inverse = TRUE,
        axisLabel = list(width = 240, overflow = "truncate", fontSize = 13))
      options$series <- list(list(name = "条目数值", type = "scatter", symbolSize = 12, itemStyle = list(color = CHART_COLORS[["purple"]]),
        data = lapply(seq_along(payload$data), function(i) list(name = payload$data[[i]]$label, label = payload$data[[i]]$label, value = c(payload$data[[i]]$value, i - 1L)))))
      options$tooltip$formatter <- htmlwidgets::JS("function(p){return p.data.label+'\\n数值: '+p.data.value[0];}")
    }
  }
  options
}

inline_widget_dependencies <- function(dependencies) {
  paste(vapply(htmltools::resolveDependencies(dependencies), function(dependency) {
    root <- dependency$src$file
    if (is.null(root)) stop("Interactive dependencies must be local", call. = FALSE)
    css <- vapply(if (is.null(dependency$stylesheet)) character() else dependency$stylesheet, function(file) paste0("<style>", paste(readLines(file.path(root, file), warn = FALSE, encoding = "UTF-8"), collapse = "\n"), "</style>"), character(1))
    scripts <- vapply(if (is.null(dependency$script)) character() else dependency$script, function(file) {
      text <- paste(readLines(file.path(root, file), warn = FALSE, encoding = "UTF-8"), collapse = "\n")
      paste0("<script>", gsub("</script", "<\\/script", text, fixed = TRUE), "</script>")
    }, character(1))
    paste(c(css, scripts), collapse = "\n")
  }, character(1)), collapse = "\n")
}

make_interactive_html <- function(payload) {
  bipartite <- is_gene_pathway_network(payload)
  height <- if (payload$chartType == "network") 960 else 740
  widget <- echarts4r::e_list(echarts4r::e_charts(renderer = "svg", height = paste0(height, "px")), interactive_options(payload))
  widget$x$chartType <- payload$chartType
  widget$x$defaultLayout <- "circular"
  widget$x$hideIsolatesByDefault <- bipartite
  widget <- htmlwidgets::onRender(widget, paste(readLines("interactive.js", warn = FALSE, encoding = "UTF-8"), collapse = "\n"))
  rendered <- htmltools::renderTags(widget)
  # Escape '<' only inside the JSON element, not its real opening/closing tags.
  opening <- regexpr('<script type="application/json"[^>]*>', rendered$html)
  closing <- tail(gregexpr('</script>', rendered$html, fixed = TRUE)[[1]], 1)
  stopifnot(opening > 0, closing > opening)
  json_start <- as.integer(opening) + attr(opening, "match.length")
  json <- substr(rendered$html, json_start, closing - 1L)
  json <- gsub("<", "\\u003c", json, fixed = TRUE)
  rendered$html <- paste0(substr(rendered$html, 1L, json_start - 1L), json, substr(rendered$html, closing, nchar(rendered$html)))
  dependencies <- paste0(inline_widget_dependencies(rendered$dependencies),
    '<style>body{font-size:16px;line-height:1.75;padding:22px}h1{font-size:22px;line-height:1.5;margin-bottom:12px}.controls{gap:14px;padding:16px}label{min-width:0;gap:7px}input,select,button{box-sizing:border-box;min-height:44px;padding:10px 12px;font-size:16px}input[type=checkbox]{min-height:20px;width:20px;height:20px}.check{gap:8px}#chart-details{padding:14px;line-height:1.75}th,td{padding:10px;line-height:1.7}@media(max-width:520px){body{padding:14px}.controls{padding:12px}.controls input:not([type=checkbox]),.controls select{max-width:100%;width:100%}h1{font-size:20px}}</style>')
  controls <- paste0(
    '<div class="controls" id="r-chart-controls"><label>搜索节点或条目<input id="chart-search" placeholder="输入名称或 ID" maxlength="120"></label><button id="chart-find">定位条目</button><button id="chart-reset">重置视图</button>',
    if (payload$chartType == "network") '<label>网络布局<select id="chart-layout"><option value="circular">圆形布局</option><option value="force">力导布局</option><option value="layered">双列 / 分层布局</option></select></label><label>最低边评分<input id="chart-score" type="number" min="0" max="1" step="0.05" value="0"></label><button id="chart-apply">应用筛选</button><label class="check"><input id="chart-labels" type="checkbox" checked>显示标签</label><label class="check"><input id="chart-isolates" type="checkbox" checked>显示孤立节点</label>' else '',
    '</div><p id="chart-status" role="status" aria-live="polite">交互图表正在加载…</p>')
  paste0('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
    '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; script-src &#39;unsafe-inline&#39; &#39;unsafe-eval&#39;; style-src &#39;unsafe-inline&#39;; img-src data: blob:; connect-src &#39;none&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">',
    '<title>', escape_html(payload$title), '</title><style>body{margin:0;padding:18px;font:400 14px/1.6 ', BROWSER_FONT_FAMILY, ';font-synthesis:none;color:#30343B;background:white}h1{font-size:19px;font-weight:600;line-height:1.4;margin:0 0 8px}h2,strong,th{font-weight:600}p{line-height:1.6;color:#68707B}.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:end;padding:12px;background:#F5F3F7;border:1px solid #E5DFEA;border-radius:8px}label{display:grid;gap:5px}input,select,button{padding:7px 10px;border:1px solid #D9D1DF;border-radius:5px;background:white;color:#30343B;font:inherit}button{cursor:pointer;font-weight:500}.check{display:flex;align-items:center;padding:8px}#chart-details{padding:10px;border-left:3px solid #70578B;min-height:24px;white-space:pre-wrap}#chart-types{display:flex;gap:12px;flex-wrap:wrap;padding:6px}details{margin-top:12px}.table-wrap{max-height:300px;overflow:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums lining-nums}th,td{padding:7px;border-bottom:1px solid #E8EAF0;text-align:left}th{position:sticky;top:0;background:#F5F3F7}</style>', dependencies,
    '</head><body><h1>', escape_html(payload$title), '</h1><p>', escape_html(payload$subtitle %||% ''), '</p>',
    controls, '<div id="chart-types"></div>', rendered$html,
    '<div id="chart-details" role="status" aria-live="polite">悬停查看数值；点击节点固定详情。滚轮缩放，拖动平移。筛选只改变显示，不改写分析结果。</div>',
    '<details><summary>查看图表对应数据表</summary>', make_data_table_html(payload), '</details></body></html>')
}
