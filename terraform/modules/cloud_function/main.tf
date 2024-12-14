# File: terraform/modules/cloud_function/main.tf

variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The region to deploy to"
  type        = string
}

variable "name" {
  description = "The name of the function"
  type        = string
}

variable "bucket_name" {
  description = "The name of the bucket to store the function code"
  type        = string
}

variable "source_dir" {
  description = "The directory containing the function source code"
  type        = string
}

variable "entry_point" {
  description = "The function entry point"
  type        = string
}

variable "runtime" {
  description = "The function runtime"
  type        = string
}

variable "environment_variables" {
  description = "Environment variables for the function"
  type        = map(string)
  default     = {}
}

# Create zip archive of function code
data "archive_file" "function_zip" {
  type        = "zip"
  output_path = "${path.module}/files/${var.name}.zip"
  source_dir  = var.source_dir
}

# Upload function code to bucket
resource "google_storage_bucket_object" "function_code" {
  name   = "${var.name}-${data.archive_file.function_zip.output_md5}.zip"
  bucket = var.bucket_name
  source = data.archive_file.function_zip.output_path
}

# Create Cloud Function
resource "google_cloudfunctions_function" "function" {
  name                  = var.name
  runtime               = var.runtime
  entry_point          = var.entry_point
  source_archive_bucket = var.bucket_name
  source_archive_object = google_storage_bucket_object.function_code.name
  trigger_http          = true
  project              = var.project_id
  region               = var.region
  available_memory_mb   = 256
  timeout              = 60
  environment_variables = var.environment_variables
}

output "function_url" {
  value = google_cloudfunctions_function.function.https_trigger_url
}

output "name" {
  value = google_cloudfunctions_function.function.name
}