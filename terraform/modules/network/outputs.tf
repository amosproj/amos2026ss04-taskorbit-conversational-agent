output "vpc_id" {
  value = google_compute_network.main.id
}

output "vpc_name" {
  value = google_compute_network.main.name
}

output "subnet_id" {
  value = google_compute_subnetwork.main.id
}

output "vpc_connector_id" {
  value = google_vpc_access_connector.main.id
}

output "private_service_connection" {
  description = "Service networking connection — database module must depend on this."
  value       = google_service_networking_connection.private_vpc_connection.id
}
