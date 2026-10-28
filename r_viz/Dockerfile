FROM rocker/r-ver:4.4.3

ENV RENV_CONFIG_CACHE_SYMLINKS=false \
    RENV_PATHS_LIBRARY=/srv/r_viz/renv/library \
    R_LIBS_USER=/srv/r_viz/bootstrap-library \
    PORT=8001

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && find /etc/apt -maxdepth 2 -type f \( -name sources.list -o -name '*.list' -o -name '*.sources' \) \
       -exec sed -i 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' {} + \
    && apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=2 update \
    && apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=2 install -y --no-install-recommends \
      ca-certificates curl cmake libuv1-dev libsodium-dev pandoc \
      libcairo2-dev libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
      libpng-dev libssl-dev libcurl4-openssl-dev libxml2-dev fonts-noto-cjk \
    && groupadd --system rviz \
    && useradd --system --gid rviz --home-dir /srv/r_viz --no-create-home rviz \
    && mkdir -p /srv/r_viz/bootstrap-library \
    && chown -R rviz:rviz /srv/r_viz

WORKDIR /srv/r_viz
COPY renv.lock ./renv.lock
USER rviz
RUN Rscript -e 'install.packages("https://cloud.r-project.org/src/contrib/Archive/renv/renv_1.3.0.tar.gz", lib = "/srv/r_viz/bootstrap-library", repos = NULL, type = "source")' \
    && Rscript -e '.libPaths(c("/srv/r_viz/bootstrap-library", .libPaths())); renv::activate(project = "/srv/r_viz"); renv::restore(project = "/srv/r_viz", prompt = FALSE)'

# Activation updates startup files; a fresh R process must restore into the
# project library selected by those files, rather than the bootstrap library.
RUN Rscript -e 'renv::restore(project = "/srv/r_viz", library = renv::paths$library(), prompt = FALSE); stopifnot(requireNamespace("plumber", quietly = TRUE), requireNamespace("echarts4r", quietly = TRUE), requireNamespace("ggplot2", quietly = TRUE))'

COPY --chown=rviz:rviz plumber.R interactive.R interactive.js ./
EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=3s --retries=3 CMD curl -fsS http://127.0.0.1:8001/health || exit 1
CMD ["Rscript", "-e", "plumber::pr_run(plumber::pr('plumber.R'), host = '0.0.0.0', port = as.integer(Sys.getenv('PORT', '8001'))) "]
