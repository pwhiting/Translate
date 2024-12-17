variable "project_id" {
  description = "The GCP project ID"
  type        = string
}
variable "region" {
  description = "The region to deploy to"
  type        = string
}
variable "translation_subscription" {
  description = "Name of the translation requests subscription"
  type        = string
}
variable "translation_topic" {
  description = "Name of the translation requests topic"
  type        = string
}
locals {
  image_tag = data.archive_file.source.output_md5
}
# Service account
resource "google_service_account" "translation_worker" {
  account_id   = "translation-worker-sa"
  display_name = "Translation Worker Service Account"
}
# Source code storage
resource "google_storage_bucket" "source_bucket" {
  name                        = "${var.project_id}-translation-worker-source"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy              = true
}
# ZIP the source code
data "archive_file" "source" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/files/translation-worker.zip"
}
# Upload source code
resource "google_storage_bucket_object" "source" {
  name   = "translation-worker-${local.image_tag}.zip"
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
        --tag=gcr.io/${var.project_id}/translation-worker:${local.image_tag}
    EOF
  }
  depends_on = [google_storage_bucket_object.source]
}
# IAM permissions for service account
resource "google_project_iam_member" "translation_worker_permissions" {
  for_each = toset([
    "roles/pubsub.publisher",
    "roles/pubsub.subscriber",
    "roles/cloudtranslate.user",
    "roles/speech.client",
    "roles/logging.logWriter",
    "roles/datastore.user",
    "roles/iam.serviceAccountUser",
    "roles/compute.networkViewer",
    "roles/run.invoker"
  ])
  
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.translation_worker.email}"
}
# Topic-specific publisher permissions
resource "google_pubsub_topic_iam_member" "translation_worker_topic_publisher" {
  project = var.project_id
  topic   = var.translation_topic
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.translation_worker.email}"
}
# Subscription-specific subscriber permissions
resource "google_pubsub_subscription_iam_member" "translation_worker_subscription_subscriber" {
  project      = var.project_id
  subscription = var.translation_subscription
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.translation_worker.email}"
}
# Add this before the service resource
resource "terraform_data" "image_version" {
  input = local.image_tag
}
# Cloud Run service
resource "google_cloud_run_v2_service" "translation_worker" {
  name     = "translation-worker"
  location = var.region
  
  template {
    service_account = google_service_account.translation_worker.email
    
    containers {
      image = "gcr.io/${var.project_id}/translation-worker:${local.image_tag}"
      
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
      
      env {
        name  = "TRANSLATION_SUB"
        value = var.translation_subscription
      }
      
      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 10
        period_seconds = 3
        failure_threshold = 3
        timeout_seconds = 3
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
    replace_triggered_by = [
      # Trigger replacement if the image tag changes
      terraform_data.image_version.id
    ]
  }
}
# Allow public access to the service
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.translation_worker.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
# Outputs
output "service_url" {
  value = google_cloud_run_v2_service.translation_worker.uri
}
output "service_name" {
  value = google_cloud_run_v2_service.translation_worker.name
}
output "service_account_email" {
  value = google_service_account.translation_worker.email
}
