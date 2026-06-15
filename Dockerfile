#FROM andres77872/ubuntu_api:20.10-12.20
#FROM andres77872/ubuntu_base:23.04-80322
FROM python:3.12

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /nn

COPY requirements.txt /nn

RUN pip install -r requirements.txt

COPY src /nn/src
COPY docs /nn/docs
COPY scripts /nn/scripts

EXPOSE 8000

# Liveness only — confirms the API answers, NOT email health, so a transient
# email degradation does not kill the container (/system/health returns 200
# regardless of component status).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/system/health',timeout=4).status==200 else 1)"

# Runs both the API server and the email outbox worker (scripts/docker-entrypoint.sh).
# Overridable for one-off runs, e.g. `docker run <img> python -m pytest`.
CMD ["bash", "scripts/docker-entrypoint.sh"]
