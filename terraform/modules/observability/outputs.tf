output "loki_url" {
  description = "Internal Cloud Run URL of the Loki service."
  value       = google_cloud_run_v2_service.loki.uri
}

output "prometheus_url" {
  description = "Internal Cloud Run URL of the Prometheus service."
  value       = google_cloud_run_v2_service.prometheus.uri
}

output "grafana_url" {
  description = "Public Grafana URL (grafana.<domain>)."
  value       = "https://grafana.${var.domain}"
}

output "grafana_lb_ip" {
  description = "Grafana load balancer IP — point grafana.<domain> DNS A record here."
  value       = google_compute_global_address.grafana_lb_ip.address
}

output "loki_logs_topic" {
  description = "Pub/Sub topic that receives Cloud Logging export for Loki ingestion."
  value       = google_pubsub_topic.loki_logs.id
}
