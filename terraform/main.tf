terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
}
# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "cloudfunctions.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "speech.googleapis.com",
    "translate.googleapis.com",
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "servicemanagement.googleapis.com",
    "servicecontrol.googleapis.com",
    "firestore.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com"
  ])
  
  project = var.project_id
  service = each.key
  disable_on_destroy = false
}
# Default service account
data "google_app_engine_default_service_account" "default" {
  project = var.project_id
}
# Storage buckets
resource "google_storage_bucket" "function_bucket" {
  name                        = "${var.project_id}-functions"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
    
  versioning {
    enabled = true
  } 
}   
# Pub/Sub Topics
resource "google_pubsub_topic" "audio_fragments" {
  name = "audio-fragments"
  message_retention_duration = "600s"  # 10 minutes
}
resource "google_pubsub_topic" "translation_requests" {
  name = "translation-requests"
  message_retention_duration = "600s"  # 10 minutes
}
# Subscription for audio fragments
resource "google_pubsub_subscription" "audio_fragments_sub" {
  name  = "audio-fragments-sub"
  topic = google_pubsub_topic.audio_fragments.name
  message_retention_duration = "600s"
  retain_acked_messages = false
  ack_deadline_seconds = 20
  expiration_policy {
    ttl = "86400s"
  }
  depends_on = [google_pubsub_topic.audio_fragments]
}
# Subscription for translation requests
resource "google_pubsub_subscription" "translation_requests_sub" {
  name  = "translation-requests-sub"
  topic = google_pubsub_topic.translation_requests.name
  message_retention_duration = "600s"
  retain_acked_messages = false
  ack_deadline_seconds = 20
  expiration_policy {
    ttl = "86400s"
  }
  depends_on = [google_pubsub_topic.translation_requests]
}
resource "google_pubsub_subscription_iam_member" "translation_requests_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.translation_requests_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:translation-worker-sa@${var.project_id}.iam.gserviceaccount.com"
  depends_on   = [
    google_pubsub_subscription.translation_requests_sub,
    module.translation_worker
  ]
}
# Cloud Functions
module "join_meeting_function" {
  source        = "./modules/cloud_function"
  project_id    = var.project_id
  region        = var.region
  name          = "join-meeting"
  bucket_name   = google_storage_bucket.function_bucket.name
  source_dir    = "${path.module}/functions/join_meeting"
  entry_point   = "join_meeting"
  runtime       = "python312"
  environment_variables = {
    PROJECT_ID = var.project_id
  }
  depends_on = [google_project_service.required_apis]
}
module "process_audio_function" {
  source        = "./modules/cloud_function"
  project_id    = var.project_id
  region        = var.region
  name          = "process-audio"
  bucket_name   = google_storage_bucket.function_bucket.name
  source_dir    = "${path.module}/functions/process_audio"
  entry_point   = "process_audio"
  runtime       = "python312"
  environment_variables = {
    PROJECT_ID = var.project_id
  }
  depends_on = [google_project_service.required_apis]
}
module "get_translations_function" {
  source        = "./modules/cloud_function"
  project_id    = var.project_id
  region        = var.region
  name          = "get-translations"
  bucket_name   = google_storage_bucket.function_bucket.name
  source_dir    = "${path.module}/functions/get_translations"
  entry_point   = "get_translations"
  runtime       = "python312"
  environment_variables = {
    PROJECT_ID = var.project_id
  }
  depends_on = [google_project_service.required_apis]
}
# Stream Manager Cloud Run Service
module "stream_manager" {
  source        = "./modules/stream_manager"
  project_id    = var.project_id
  region        = var.region
  translation_topic = google_pubsub_topic.translation_requests.name
  audio_subscription = google_pubsub_subscription.audio_fragments_sub.name
  depends_on = [
    google_project_service.required_apis,
    google_pubsub_topic.translation_requests,
    google_pubsub_subscription.audio_fragments_sub
  ]
}
# Translation Worker Cloud Run Service
module "translation_worker" {
  source     = "./modules/translation_worker"
  project_id = var.project_id
  region     = var.region
  translation_subscription = google_pubsub_subscription.translation_requests_sub.name
  translation_topic = google_pubsub_topic.translation_requests.name
  depends_on = [
    google_project_service.required_apis,
    google_pubsub_topic.translation_requests,
    google_pubsub_subscription.translation_requests_sub
  ]
}
module "cleanup_meetings_function" {
  source        = "./modules/cleanup_meetings"
  project_id    = var.project_id
  region        = var.region
  name          = "cleanup-meetings"
  bucket_name   = google_storage_bucket.function_bucket.name
  source_dir    = "${path.module}/functions/cleanup_meetings"
  entry_point   = "cleanup_meetings"
  runtime       = "python312"
  environment_variables = {
    PROJECT_ID = var.project_id
    INACTIVE_THRESHOLD_HOURS = "1"
  }
  depends_on = [google_project_service.required_apis]
}
# Cloud Scheduler for cleanup
resource "google_cloud_scheduler_job" "cleanup_job" {
  name             = "meeting-cleanup"
  description      = "Periodically clean up inactive meetings"
  schedule         = "0 * * * *"  # Run hourly
  time_zone        = "UTC"
  attempt_deadline = "300s"
  http_target {
    http_method = "POST"
    uri         = module.cleanup_meetings_function.function_url
    
    oidc_token {
      service_account_email = data.google_app_engine_default_service_account.default.email
    }
  }
  depends_on = [google_project_service.required_apis]
}
# IAM bindings
resource "google_project_iam_member" "speech_client" {
  project = var.project_id
  role    = "roles/cloudtranslate.user"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}
resource "google_project_iam_member" "speech_to_text" {
  project = var.project_id
  role    = "roles/speech.client"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}
resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}
resource "google_project_iam_member" "pubsub_subscriber" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}


# Add to main.tf
module "leave_meeting_function" {
  source        = "./modules/cloud_function"
  project_id    = var.project_id
  region        = var.region
  name          = "leave-meeting"
  bucket_name   = google_storage_bucket.function_bucket.name
  source_dir    = "${path.module}/functions/leave_meeting"
  entry_point   = "leave_meeting"
  runtime       = "python312"
  environment_variables = {
    PROJECT_ID = var.project_id
  }
  depends_on = [google_project_service.required_apis]
}

# Add IAM binding for the leave function
resource "google_cloudfunctions_function_iam_member" "leave_meeting_invoker" {
  project        = var.project_id
  region         = var.region
  cloud_function = module.leave_meeting_function.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}


# Function IAM permissions
resource "google_cloudfunctions_function_iam_member" "join_meeting_invoker" {
  project        = var.project_id
  region         = var.region
  cloud_function = module.join_meeting_function.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}
resource "google_cloudfunctions_function_iam_member" "process_audio_invoker" {
  project        = var.project_id
  region         = var.region
  cloud_function = module.process_audio_function.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}
resource "google_cloudfunctions_function_iam_member" "get_translations_invoker" {
  project        = var.project_id
  region         = var.region
  cloud_function = module.get_translations_function.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}
