variable "project_id" { type = string }
variable "region" { type = string }
variable "db_instance_name" { type = string }

variable "enable_auto_shutdown" {
  description = "Enable Cloud Scheduler jobs that stop Cloud SQL and (optionally) scale down the worker overnight."
  type        = bool
  default     = true
}

variable "scale_worker_overnight" {
  description = "Also scale the LiveKit worker to 0 overnight. Drops active voice rooms — only enable if 24/7 availability is not required."
  type        = bool
  default     = false
}

variable "sql_stop_cron" {
  description = "Cron expression for stopping Cloud SQL (time_zone applies)."
  type        = string
  default     = "0 22 * * 1-5"  # 22:00 Mon–Fri
}

variable "sql_start_cron" {
  description = "Cron expression for starting Cloud SQL."
  type        = string
  default     = "0 7 * * 1-5"   # 07:00 Mon–Fri
}

variable "time_zone" {
  description = "IANA time zone for cron schedules."
  type        = string
  default     = "Europe/Berlin"
}
