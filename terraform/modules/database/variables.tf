variable "project_id" { type = string }
variable "region" { type = string }
variable "network_id" {
  description = "VPC network ID for the private service connection."
  type        = string
}
