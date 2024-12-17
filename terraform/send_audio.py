import base64
import json
import requests

# Read and encode the audio file
with open('your_file.wav', 'rb') as f:
    audio_data = base64.b64encode(f.read()).decode('utf-8')

# Prepare the request
url = "https://us-central1-translate-444611.cloudfunctions.net/process-audio"
headers = {"Content-Type": "application/json"}
data = {
    "meetingCode": "TEST01",
    "sourceLanguage": "en-US",
    "audioData": audio_data,
    "clientId": "97fdda3d-8a65-4f86-a8b3-6484ed9c2a01"  # Using the Spanish listener's clientId
}

# Send the request
response = requests.post(url, headers=headers, json=data)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.json()}")