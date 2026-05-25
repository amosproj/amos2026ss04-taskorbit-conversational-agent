# ── VPC ───────────────────────────────────────────────────────────────────────

resource "google_compute_network" "main" {
  name                    = "taskorbit-vpc"
  auto_create_subnetworks = false
  project                 = var.project_id
}

resource "google_compute_subnetwork" "main" {
  name                     = "taskorbit-subnet"
  ip_cidr_range            = "10.10.0.0/24"
  region                   = var.region
  network                  = google_compute_network.main.id
  project                  = var.project_id
  private_ip_google_access = true
}

# ── Private service access (Cloud SQL private IP) ─────────────────────────────

resource "google_compute_global_address" "private_service_range" {
  name          = "taskorbit-private-service-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
  project       = var.project_id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_range.name]

  deletion_policy = "ABANDON"
}

# ── Cloud Router + NAT (outbound internet for Cloud Run VPC egress) ───────────

resource "google_compute_router" "main" {
  name    = "taskorbit-router"
  region  = var.region
  network = google_compute_network.main.id
  project = var.project_id
}

resource "google_compute_router_nat" "main" {
  name                               = "taskorbit-nat"
  router                             = google_compute_router.main.name
  region                             = var.region
  project                            = var.project_id
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# ── Serverless VPC Access connector (Cloud Run → Cloud SQL via private IP) ─────

resource "google_vpc_access_connector" "main" {
  name          = "taskorbit-connector"
  region        = var.region
  project       = var.project_id
  network       = google_compute_network.main.name
  ip_cidr_range = "10.8.0.0/28"

  min_instances = 2
  max_instances = 10
  machine_type  = "e2-micro"

  depends_on = [google_compute_subnetwork.main]
}

# ── Firewall rules ────────────────────────────────────────────────────────────

resource "google_compute_firewall" "allow_internal" {
  name    = "taskorbit-allow-internal"
  network = google_compute_network.main.name
  project = var.project_id

  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = ["10.10.0.0/24", "10.8.0.0/28"]
}

# Required for GCP load balancer health checks
resource "google_compute_firewall" "allow_health_checks" {
  name    = "taskorbit-allow-health-checks"
  network = google_compute_network.main.name
  project = var.project_id

  allow {
    protocol = "tcp"
  }

  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
}
