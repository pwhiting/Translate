# Real-time Translation Meeting System Requirements

## System Overview
A real-time audio translation system that enables a host to speak in their native language while participants listen to translations in their preferred languages. The system supports multiple concurrent meetings, dynamic language selection, and mid-meeting language additions.

## Technical Stack
- iOS Client: SwiftUI-based application
- Backend: Google Cloud Platform
  - Cloud Functions (Python 3.12)
  - Cloud Firestore
  - Cloud Storage
  - Speech-to-Text API
  - Translation API
  - API Gateway
- Infrastructure: Terraform

## Project Structure
```
project/
├── ios/
│   └── TranslationApp.swift
│   └── info.plist.xml
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── api_spec.yaml
│   ├── modules/
│   │   └── cloud_function/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       └── outputs.tf
│   └── functions/
│       ├── process_audio/
│       │   ├── main.py
│       │   ├── requirements.txt
│       │   └── function.json
│       ├── join_meeting/
│       │   ├── main.py
│       │   ├── requirements.txt
│       │   └── function.json
│       └── get_translations/
│           ├── main.py
│           ├── requirements.txt
│           └── function.json
```

## Core Features

### Meeting Management
- 6-character uppercase meeting codes (randomly generated)
- Dynamic participant joining/leaving
- Support for multiple concurrent meetings
- Mid-meeting language additions
- Real-time status updates

### Audio Processing
- Continuous audio capture (iOS microphone)
- Audio chunking (1-2 second intervals)
- Linear16 encoding, 16000Hz sample rate
- Mono channel audio
- Buffer management for optimal sentence detection

### Translation Pipeline
1. Speech-to-Text conversion
2. Language-specific sentence boundary detection
3. Multi-language translation
4. Translation caching
5. Efficient storage in Firestore
6. Real-time delivery to participants

### Speech Output
- Dynamic rate adjustment based on:
  - Current delay from source
  - Target language characteristics
  - User preferences
  - Maximum comprehensibility limits
- Pitch adjustment for faster speech
- Visual delay indicators
- Language-specific voice selection

## Data Models

### Meeting Document
```json
{
    "code": "ABCDEF",
    "hostLanguage": "en-US",
    "status": "active",
    "startTime": timestamp,
    "targetLanguages": ["ko", "es", "fr"],
    "participants": {
        "p1234567890": "ko",
        "p1234567891": "es"
    }
}
```

### Translation Document
```json
{
    "sourceText": "original text",
    "sourceLanguage": "en-US",
    "targetLanguage": "ko",
    "translatedText": "translated text",
    "timestamp": server_timestamp,
    "isComplete": true
}
```

## API Endpoints

### Join Meeting
- POST /join
```json
Request:
{
    "meetingCode": "ABCDEF",
    "targetLanguage": "ko"
}

Response:
{
    "success": true,
    "participantId": "p1234567890"
}
```

### Process Audio
- POST /audio
```json
Request:
{
    "meetingCode": "ABCDEF",
    "sourceLanguage": "en-US",
    "audioData": "base64_encoded_audio"
}

Response:
{
    "success": true,
    "transcription": "text"
}
```
### Get Translations (first request)
- GET /translations?meetingCode=ABCDEF&targetLanguage=ko
```json
Response:
{
    "success": true,
    "translations": [
        {
            "id": "doc_id",
            "messageId": "doc_id",
            "translatedText": "translated text",
            "sourceLanguage": "en-US",
            "targetLanguage": "ko",
            "timestamp": 1234567890.123,
            "isComplete": true,
            "empty": false
        }
    ]
}

### Get Translations (after first request)
- GET /translations?meetingCode=ABCDEF&targetLanguage=ko&timestamp=1234567800.1
```json
Response:
{
    "success": true,
    "translations": [
        {
            "id": "doc_id",
            "messageId": "doc_id",
            "translatedText": "translated text",
            "sourceLanguage": "en-US",
            "targetLanguage": "ko",
            "timestamp": 1234567890.123,
            "isComplete": true,
            "empty": false
        }
    ]
}
```

## Infrastructure Details

### Required Google Cloud APIs
- Cloud Functions
- Cloud Resource Manager
- Cloud Build
- Speech-to-Text
- Translation
- API Gateway
- Service Management
- Service Control
- Firestore

### Storage Configuration
- Function code bucket: Versioning enabled
- Audio storage bucket: 1 minute retention policy

### Cloud Functions Configuration
- Runtime: Python 3.12
- Memory: 256MB
- Timeout: 60 seconds
- HTTP Triggers
- Environment Variables:
  - AUDIO_BUCKET: Audio storage bucket name

## iOS App Features

### Host Interface
- Meeting code display
- Source language selection
- Audio level visualization
- Start/stop controls
- Real-time transcription display
- Status indicators
- Error handling

### Participant Interface
- Meeting code entry
- Target language selection
- Real-time translation display
- Audio/text toggle
- Delay indicator
- Speaking rate preferences
- Volume control

## Language Support

### Source Languages (Initial)
- English (en-US)
- Spanish (es)
- French (fr)
- German (de)
- Japanese (ja)
- Chinese (zh)
- Korean (ko)

### Text-to-Speech Voices for testing
- Korean: Yuna
- Spanish: Monica
- French: Thomas
- English: Default system voice

## Performance Requirements
- Maximum audio processing latency: 3 seconds
- Maximum translation latency: 5 seconds
- Maximum end-to-end latency: 10 seconds
- Support up to 100 concurrent participants per meeting
- Support up to 50 concurrent meetings

## Testing Tools

### Test Script Features
- Random meeting code generation
- Audio recording (sox)
- Base64 encoding (osx syntax: -i input_file -o output_file)
- API endpoint testing
- Multi-language support
- Audio playback
- Translation verification

### Test Script Dependencies
- sox (audio recording)
- curl (API testing)
- python3 (JSON processing)
- macOS text-to-speech

## Development and Deployment Steps

1. Infrastructure Setup
```bash
# Enable required APIs
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable speech.googleapis.com
gcloud services enable translate.googleapis.com
gcloud services enable apigateway.googleapis.com
gcloud services enable servicemanagement.googleapis.com
gcloud services enable servicecontrol.googleapis.com
gcloud services enable firestore.googleapis.com
```

2. Deploy Infrastructure
```bash
cd terraform
terraform init
terraform apply
```

3. Test Deployment
```bash
# Get API URL
python3 test-service.py
```



## Translation Retrieval Logic

### Sequence Tracking
- Each meeting maintains a global sequence counter in the metadata collection
- Each translation is assigned a unique, monotonically increasing sequence number
- Sequence numbers are assigned atomically using Firestore transactions
- Clients track the last sequence number they've received for their language

### Initial Connection
When a participant first joins a meeting, they make an initial GET request to /translations without a sequence parameter. This request serves to register their interest in a specific language. The response will be an empty translation object with empty=true and sequence=0.

### Subsequent Requests
All subsequent requests must include the last_sequence parameter from their previous response. The server processes these requests as follows:

1. Retrieves all translation entries where:
   - sequence > last_sequence
   - targetLanguage matches the requested language
   - meetingCode matches the current meeting

2. If translations are found:
   - Orders translations by sequence number (ascending)
   - Concatenates the translatedText fields in sequence order
   - Uses the highest sequence from the set as the response sequence
   - Returns a single translation object containing:
     - The concatenated text
     - The highest sequence number
     - empty=false

3. If no translations are found:
   - Server holds the request for up to 15 seconds waiting for new translations
   - If no translations arrive during wait period, returns:
     - empty=true
     - translatedText=""
     - sequence matching the request's last_sequence

### Example Response Flow

```json
// First request (no sequence) - Registration
GET /translations?meetingCode=ABCDEF&targetLanguage=ko
Response:
{
    "success": true,
    "translations": [
        {
            "id": "registration",
            "messageId": "registration",
            "translatedText": "",
            "sourceLanguage": "",
            "targetLanguage": "ko",
            "sequence": 0,
            "isComplete": true,
            "empty": true
        }
    ]
}

// Second request - New content available
GET /translations?meetingCode=ABCDEF&targetLanguage=ko&sequence=0
Response:
{
    "success": true,
    "translations": [
        {
            "id": "concat_123",
            "messageId": "concat_123",
            "translatedText": "첫 번째 문장. 두 번째 문장. 세 번째 문장.",
            "sourceLanguage": "en-US",
            "targetLanguage": "ko",
            "sequence": 3,
            "isComplete": true,
            "empty": false
        }
    ]
}

// Third request - No new content
GET /translations?meetingCode=ABCDEF&targetLanguage=ko&sequence=3
Response:
{
    "success": true,
    "translations": [
        {
            "id": "empty_123",
            "messageId": "empty_123",
            "translatedText": "",
            "sourceLanguage": "",
            "targetLanguage": "ko",
            "sequence": 3,
            "isComplete": true,
            "empty": true
        }
    ]
}
```

### Data Models

#### Meeting Document
```json
{
    "code": "ABCDEF",
    "hostLanguage": "en-US",
    "status": "active",
    "targetLanguages": ["ko", "es", "fr"],
    "participants": {
        "p1234567890": "ko",
        "p1234567891": "es"
    }
}
```

#### Translation Document
```json
{
    "sourceText": "original text",
    "sourceLanguage": "en-US",
    "targetLanguage": "ko",
    "translatedText": "translated text",
    "sequence": 42,
    "isComplete": true
}
```

#### Meeting Metadata Document
```json
{
    "currentSequence": 42
}
```






## Important Implementation Notes
1. Meeting creation occurs on first join 
2. Translations are stored per language
3. Use SERVER_TIMESTAMP for consistent timing
4. Store translations atomically using batched writes
5. Query translations by target language
6. Handle mid-meeting language additions
7. Implement proper error handling and logging
8. Use appropriate voice selection per language
9. Implement rate adaptation for delay management


## Info on test script

Create a test script, test-service.py that does the following, emulating both the host and the listeners. Include robust debugging information, including calling gcloud cli to output logs from the stuff running in google.

the script does the following
1. joins the meeting in korean and spanish as listeners
1. starts hosting the meeting by sending in an audio file named hike.base64.
1. for each korean and spanish
1.1 use curl to grab the translated frames, 
1. french joins the meeting
1. host sends in another audio file hungry.base64
1. for each language
1.1 use curl to grab the translated content subsequent to what they already downloaded and print each out

the script can be python

## files in output

For the initial generation task generate the following files:

project/
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
|   ├── test-service.py
│   ├── api_spec.yaml
│   ├── modules/
│   │   └── cloud_function/
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       └── outputs.tf
│   └── functions/
│       ├── process_audio/
│       │   ├── main.py
│       │   ├── requirements.txt
│       │   └── function.json
│       ├── join_meeting/
│       │   ├── main.py
│       │   ├── requirements.txt
│       │   └── function.json
│       └── get_translations/
│           ├── main.py
│           ├── requirements.txt
│           └── function.json


Output these in as a single file with
# File: filename
seperating each file in that large aggregate. For example:

# File: terraform/main.tf
[contents of main.tf here]

# File: terraform/functions/process_audio/main.py
[contents of main.py here]



