# Provider configuration
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

# Data sources
data "google_app_engine_default_service_account" "default" {
  project = var.project_id
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
    "servicemanagement.googleapis.com",
    "servicecontrol.googleapis.com",
    "firestore.googleapis.com",
    "artifactregistry.googleapis.com"
  ])
  
  project = var.project_id
  service = each.key
  disable_on_destroy = false
}

/* # Firestore Configuration
resource "google_firestore_database" "database" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required_apis]
}
 */
# Firestore TTL configuration
resource "google_firestore_field" "timestamp_ttl" {
  project    = var.project_id
  database   = "(default)"
  collection = "meetings"  # Changed from meetings/{meetingId}/translations
  field      = "timestamp"
  ttl_config {}
}

# Firestore index for translations
resource "google_firestore_index" "meeting_translations_index" {
  project    = var.project_id
  database   = "(default)"
  collection = "meetings"  # Changed from meetings/{meetingId}/translations
  
  fields {
    field_path = "translations.targetLanguage"
    order      = "ASCENDING"
  }
  
  fields {
    field_path = "translations.isComplete"
    order      = "ASCENDING"
  }
  
  fields {
    field_path = "translations.timestamp"
    order      = "ASCENDING"
  }

  depends_on = [google_project_service.required_apis]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_firestore_index" "translations_query_index" {
  project    = var.project_id
  database   = "(default)"
  collection = "meetings_translations"  # Changed to a static collection path
  
  fields {
    field_path = "targetLanguage"
    order      = "ASCENDING"
  }
  
  fields {
    field_path = "isComplete"
    order      = "ASCENDING"
  }
  
  fields {
    field_path = "sequence"
    order      = "ASCENDING"
  }

  depends_on = [google_project_service.required_apis]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_firestore_index" "translations_composite_index" {
  project    = var.project_id
  database   = "(default)"
  collection = "translations"

  fields {
    field_path = "isComplete"
    order      = "ASCENDING"
  }

  fields {
    field_path = "targetLanguage"
    order      = "ASCENDING"
  }

  fields {
    field_path = "sequence"
    order      = "ASCENDING"
  }

  depends_on = [google_project_service.required_apis]

  lifecycle {
    prevent_destroy = true
  }
}
# IAM Permissions
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

resource "google_project_iam_member" "translation_api" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}

resource "google_project_iam_member" "cloudfunctions_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}

resource "google_project_iam_member" "cloudfunctions_service_account_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
}

resource "google_project_iam_member" "cloudfunctions_developer" {
  project = var.project_id
  role    = "roles/cloudfunctions.developer"
  member  = "serviceAccount:${data.google_app_engine_default_service_account.default.email}"
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

resource "google_storage_bucket" "audio_bucket" {
  name                        = "${var.project_id}-audio"
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "Delete"
    }
  }
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
    AUDIO_BUCKET = google_storage_bucket.audio_bucket.name
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
    AUDIO_BUCKET = google_storage_bucket.audio_bucket.name
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
    AUDIO_BUCKET = google_storage_bucket.audio_bucket.name
  }
  depends_on = [google_project_service.required_apis]
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