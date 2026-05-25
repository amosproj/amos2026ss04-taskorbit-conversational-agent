output "backend_url" {
  description = "Cloud Run service URL for the backend (internal, not the LB URL)."
  value       = google_cloud_run_v2_service.backend.uri
}

output "worker_url" {
  description = "Cloud Run service URL for the LiveKit worker."
  value       = google_cloud_run_v2_service.worker.uri
}

output "frontend_url" {
  description = "Cloud Run service URL for the frontend (internal, not the LB URL)."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "load_balancer_ip" {
  description = "Global external IP — point DNS A records for the domain here."
  value       = google_compute_global_address.lb_ip.address
}
