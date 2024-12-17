variable "project_id" {
  description = "The GCP project ID"
  type        = string
}
variable "region" {
  description = "The region to deploy to"
  type        = string
}
variable "translation_topic" {
  description = "Name of the translation requests topic"
  type        = string
}
variable "audio_subscription" {
  description = "Name of the audio fragments subscription"
  type        = string
}
locals {
  image_tag = data.archive_file.source.output_md5
}
# Service account
resource "google_service_account" "stream_manager" {
  account_id   = "stream-manager-sa"
  display_name = "Stream Manager Service Account"
}
# Source code storage
resource "google_storage_bucket" "source_bucket" {
  name                        = "${var.project_id}-stream-manager-source"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy              = true
}
# ZIP the source code
data "archive_file" "source" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/files/stream-manager.zip"
}
# Upload source code
resource "google_storage_bucket_object" "source" {
  name   = "stream-manager-${local.image_tag}.zip"
  bucket = google_storage_bucket.source_bucket.name
  source = data.archive_file.source.output_path
  content_type = "application/zip"
  metadata = {
    hash = local.image_tag
  }
}
# Build the container image
resource "null_resource" "build_image" {
  triggers = {
    source_hash = local.image_tag
  }
  provisioner "local-exec" {
    command = <<EOF
      gcloud builds submit ${path.module}/src \
        --project=${var.project_id} \
        --tag=gcr.io/${var.project_id}/stream-manager:${local.image_tag}
    EOF
  }
  depends_on = [google_storage_bucket_object.source]
}
# IAM permissions for service account
resource "google_project_iam_member" "stream_manager_permissions" {
  for_each = toset([
    "roles/speech.client",
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/logging.logWriter",
    "roles/iam.serviceAccountUser",    
    "roles/compute.networkViewer",
    "roles/compute.viewer",
    "roles/run.invoker"
  ])
  
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.stream_manager.email}"
}
# Add explicit topic permissions
resource "google_pubsub_topic_iam_member" "stream_manager_topic_publisher" {
  project = var.project_id
  topic   = var.translation_topic
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.stream_manager.email}"
}
# Add explicit subscription permissions
resource "google_pubsub_subscription_iam_member" "stream_manager_subscription_subscriber" {
  project      = var.project_id
  subscription = var.audio_subscription
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.stream_manager.email}"
}
# Cloud Run service
resource "google_cloud_run_v2_service" "stream_manager" {
  name     = "stream-manager"
  location = var.region
  template {
    service_account = google_service_account.stream_manager.email
    
    containers {
      image = "gcr.io/${var.project_id}/stream-manager:${local.image_tag}"
      
      resources {
        cpu_idle = true
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }
      
      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      
      env {
        name  = "CODE_VERSION"
        value = local.image_tag
      }
      
      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        timeout_seconds = 3
        period_seconds = 5
        failure_threshold = 3
      }
      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 600
      }
    }
    
    max_instance_request_concurrency = 80
    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }
  }
  
  depends_on = [null_resource.build_image]
  lifecycle {
    create_before_destroy = true
  }
}
# Allow public access to the service
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.stream_manager.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
# Outputs
output "service_url" {
  value = google_cloud_run_v2_service.stream_manager.uri
}
output "service_name" {
  value = google_cloud_run_v2_service.stream_manager.name
}
output "service_account_email" {
  value = google_service_account.stream_manager.email
}
