variable "project_id" {
  description = "The GCP project ID"
  type        = string
}
variable "region" {
  description = "The region to deploy resources to"
  type        = string
  default     = "us-central1"
}
variable "environment" {
  description = "The environment (dev, prod)"
  type        = string
  default     = "dev"
}
