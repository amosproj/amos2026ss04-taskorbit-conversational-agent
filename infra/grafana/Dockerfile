FROM grafana/grafana:11.3.0
# Bake provisioning files into the image so they are available on Cloud Run
# where there is no Docker socket or bind-mount.
# Datasource URLs are injected at runtime via PROMETHEUS_URL and LOKI_URL env vars
# which Grafana substitutes automatically in provisioning YAML files.
COPY provisioning /etc/grafana/provisioning
