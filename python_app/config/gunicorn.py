"""WSGI process controls shared by production and local proxy acceptance."""
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8020")
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100
# Runtime control is not exposed; deployments manage workers via the container.
control_socket_disable = True
accesslog = "-"
errorlog = "-"
# Never write verification tokens or private search terms from query strings.
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s request_id=%({x-request-id}o)s'
