FROM rocker/r-ver:4.4.3

ENV RENV_CONFIG_CACHE_SYMLINKS=false \
    RENV_PATHS_LIBRARY=/srv/r_viz/renv/library \
    R_LIBS_USER=/srv/r_viz/bootstrap-library \
    PORT=8001

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
      libcairo2-dev libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
      libpng-dev libssl-dev libcurl4-openssl-dev libxml2-dev fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system rviz \
    && useradd --system --gid rviz --home-dir /srv/r_viz --no-create-home rviz \
    && mkdir -p /srv/r_viz/bootstrap-library \
    && chown -R rviz:rviz /srv/r_viz

WORKDIR /srv/r_viz
COPY renv.lock ./renv.lock
USER rviz
RUN Rscript -e 'install.packages("https://cloud.r-project.org/src/contrib/renv_1.3.0.tar.gz", repos = NULL, type = "source")' \
    && Rscript -e 'renv::activate(project = "/srv/r_viz"); renv::restore(project = "/srv/r_viz", prompt = FALSE)'

COPY --chown=rviz:rviz plumber.R ./plumber.R
EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=3s --retries=3 CMD curl -fsS http://127.0.0.1:8001/health || exit 1
CMD ["Rscript", "-e", "plumber::pr_run(plumber::pr('plumber.R'), host = '0.0.0.0', port = as.integer(Sys.getenv('PORT', '8001'))) "]
