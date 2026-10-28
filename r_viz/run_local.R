# Existing local R installation; keep preview bound to loopback only.
if (.Platform$OS.type == "windows") Sys.setlocale("LC_CTYPE", "Chinese (Simplified)_China.utf8")
plumber::pr_run(plumber::pr("plumber.R"), host = "127.0.0.1", port = as.integer(Sys.getenv("PORT", "8001")))
