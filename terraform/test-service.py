# File: test-service.py
import os
import json
import time
import subprocess
import requests
import base64
from datetime import datetime

# Global config
SHOW_LOGS = True  # Set to True to see full gcloud logs

def run_command(cmd):
    """Run a shell command and return output."""
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    return stdout.decode().strip(), stderr.decode()

def get_function_urls():
    """Get the Cloud Function URLs from Terraform outputs."""
    urls = {}
    for function in ['join_meeting_url', 'process_audio_url', 'get_translations_url', 'leave_meeting_url']:
        stdout, _ = run_command(f'terraform output -raw {function}')
        if not stdout:
            raise ValueError(f"Could not get URL for {function} from terraform output")
        urls[function] = stdout.strip()
    return urls

def check_logs(wait_time=0):
    """Get and display logs from all services."""
    if not SHOW_LOGS:
        if wait_time > 0:
            print(f"\nProcessing... (waiting {wait_time}s)")
            time.sleep(wait_time)
        return

    if wait_time > 0:
        print(f"\nWaiting {wait_time} seconds for logs to propagate...")
        time.sleep(wait_time)

    # Process Audio Function logs
    print("\n=== Cloud Function Logs ===")
    cmd = 'gcloud functions logs read process-audio --project=translate-444611 --limit=20'
    stdout, stderr = run_command(cmd)
    if stdout:
        print("\nProcess Audio Logs:")
        print(stdout)
    if stderr:
        print("Process Audio Errors:", stderr)

    # Stream Manager logs
    print("\n=== Stream Manager Logs ===")
    cmd = 'gcloud run services logs read stream-manager --project=translate-444611 --region=us-central1 --limit=20'
    stdout, stderr = run_command(cmd)
    if stdout:
        print("\nStream Manager Logs:")
        print(stdout)
    if stderr:
        print("Stream Manager Errors:", stderr)

    # Translation Worker logs
    print("\n=== Translation Worker Logs ===")
    cmd = 'gcloud run services logs read translation-worker --project=translate-444611 --region=us-central1 --limit=20'
    stdout, stderr = run_command(cmd)
    if stdout:
        print("\nTranslation Worker Logs:")
        # Parse and format translation worker logs for better readability
        for line in stdout.split('\n'):
            if '[DEBUG]' in line:
                print('\033[36m' + line + '\033[0m')  # Cyan for debug
            elif '[ERROR]' in line:
                print('\033[91m' + line + '\033[0m')  # Red for errors
            elif '[WARNING]' in line:
                print('\033[93m' + line + '\033[0m')  # Yellow for warnings
            elif '✓' in line:
                print('\033[92m' + line + '\033[0m')  # Green for success
            elif '✗' in line:
                print('\033[91m' + line + '\033[0m')  # Red for failure
            else:
                print(line)
    if stderr:
        print("Translation Worker Errors:", stderr)

    if stdout:
        # Print message flow summary
        print("\n=== Message Flow Summary ===")
        try:
            # Extract timestamps from logs to show message flow
            stream_timestamps = extract_timestamps(stdout, "Stream Manager")
            translation_timestamps = extract_timestamps(stdout, "Translation Worker")
            
            if stream_timestamps and translation_timestamps:
                print("\nMessage Flow Timeline:")
                for stream_time, trans_time in zip(stream_timestamps, translation_timestamps):
                    delay = trans_time - stream_time
                    print(f"Stream Manager → Translation Worker: {delay:.2f}s")
        except Exception as e:
            print(f"Could not generate message flow summary: {str(e)}")

def extract_timestamps(logs, service_name):
    """Extract timestamps from log entries for timing analysis."""
    timestamps = []
    if not logs:
        return timestamps
        
    for line in logs.split('\n'):
        if "Processing message" in line and service_name in line:
            try:
                # Extract timestamp from log line
                timestamp_str = line.split('[')[0].strip()
                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                timestamps.append(timestamp.timestamp())
            except Exception:
                continue
    return timestamps

class TranslationTester:
    def __init__(self, urls):
        self.urls = urls
        self.clients = {}
        print("\n=== Initializing Translation Test ===")
        print("Initializing speaker...")
        response = self.join_meeting("TEST01", "en-US")
        self.speaker_client = response['clientId']
        print(f"✓ Speaker initialized with client ID: {self.speaker_client}")
    
    def join_meeting(self, meeting_code, language):
        """Join a meeting with specified language."""
        print(f"\n=== Joining Meeting ===")
        print(f"Meeting Code: {meeting_code}")
        print(f"Language: {language}")
        
        response = requests.post(
            self.urls['join_meeting_url'],
            json={
                'meetingCode': meeting_code,
                'targetLanguage': language
            }
        )
        print(f"Join meeting response status: {response.status_code}")
        data = response.json()
        
        if data.get('success'):
            client_id = data['clientId']
            if language != "en-US":  # Don't store speaker in listeners
                self.clients[language] = client_id
            print(f"✓ Successfully joined meeting {meeting_code}")
            print(f"Client ID: {client_id}")
            print(f"Language: {language}")
            print(f"Subscription path: {data.get('subscriptionPath')}")
        else:
            print(f"✗ Failed to join meeting: {data.get('error', 'Unknown error')}")
        
        return data

    def leave_meeting(self, meeting_code, language, client_id=None):
        """Leave a meeting for a specific language and client."""
        print(f"\n=== Leaving Meeting ===")
        print(f"Meeting Code: {meeting_code}")
        print(f"Language: {language}")
        
        if client_id is None:
            if language == "en-US":
                client_id = self.speaker_client
            else:
                client_id = self.clients.get(language)
                if not client_id:
                    print(f"✗ No client ID found for language {language}")
                    return None
        
        print(f"Client ID: {client_id}")
        
        response = requests.post(
            self.urls['leave_meeting_url'],
            json={
                'meetingCode': meeting_code,
                'targetLanguage': language,
                'clientId': client_id
            }
        )
        
        print(f"Leave meeting response status: {response.status_code}")
        data = response.json()
        
        if data.get('success'):
            print(f"✓ Successfully left meeting {meeting_code}")
            if language in self.clients:
                del self.clients[language]
        else:
            print(f"✗ Failed to leave meeting: {data.get('error', 'Unknown error')}")
        
        return data
    
    def send_audio(self, meeting_code, audio_file):
        """Send audio file for translation with enhanced logging."""
        wav_file = audio_file
        if audio_file.endswith('.base64'):
            wav_file = audio_file.replace('.base64', '.wav')
        
        try:
            with open(wav_file, 'rb') as f:
                audio_data = base64.b64encode(f.read()).decode('utf-8')
            
            print(f"\n=== Sending Audio File ===")
            print(f"File: {wav_file}")
            print(f"Encoded length: {len(audio_data)} bytes")
            print(f"Speaker client ID: {self.speaker_client}")
            print(f"Meeting code: {meeting_code}")
            
            request_data = {
                'meetingCode': meeting_code,
                'sourceLanguage': 'en-US',
                'audioData': audio_data,
                'clientId': self.speaker_client
            }
            
            print("\nSending request to process-audio function...")
            response = requests.post(
                self.urls['process_audio_url'],
                json=request_data
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    print("\n✓ Audio processing success:")
                    print(f"Message ID: {data.get('messageId', 'N/A')}")
                    print(f"Audio size: {data.get('audioSize', 'N/A')} bytes")
                    print(f"Timestamp: {data.get('timestamp', 'N/A')}")
                else:
                    print(f"\n✗ Error processing audio: {data.get('error', 'Unknown error')}")
            else:
                print(f"\n✗ HTTP Error {response.status_code}: {response.text}")
            
            return response.json() if response.status_code == 200 else None
            
        except FileNotFoundError:
            print(f"\n✗ Error: Could not find audio file {wav_file}")
            print("Make sure you have the WAV files (hike.wav and hungry.wav)")
            raise
        except Exception as e:
            print(f"\n✗ Error processing audio file: {str(e)}")
            raise
    
    def get_translations(self, meeting_code, language):
        """Get translations with enhanced logging."""
        if language not in self.clients:
            print(f"\n✗ Error: No client ID found for language {language}")
            return None
            
        params = {
            'meetingCode': meeting_code,
            'targetLanguage': language,
            'clientId': self.clients[language]
        }
        
        try:
            print(f"\n=== Checking Translations for {language.upper()} ===")
            print(f"Client ID: {self.clients[language]}")
            
            response = requests.get(
                self.urls['get_translations_url'],
                params=params,
                timeout=20
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    translations = data.get('translations', [])
                    if translations:
                        print(f"\n✓ Received {len(translations)} translation(s):")
                        for translation in translations:
                            print("\nTranslation Details:")
                            print(f"Message ID: {translation.get('messageId', 'N/A')}")
                            # Decode unicode escapes in translation text
                            translated_text = translation.get('translatedText', 'N/A')
                            if isinstance(translated_text, str):
                                translated_text = bytes(translated_text, 'utf-8').decode('unicode_escape')
                            print(f"Text: {translated_text}")
                            print(f"Source Language: {translation.get('attributes', {}).get('sourceLanguage', 'N/A')}")
                            print(f"Timestamp: {translation.get('timestamp', 'N/A')}")
                    else:
                        print(f"\n⚠ No new translations for {language}")
                else:
                    print(f"\n✗ Error: {data.get('error', 'Unknown error')}")
            else:
                print(f"\n✗ HTTP Error {response.status_code}: {response.text}")
            
            return response.json() if response.status_code == 200 else None
            
        except requests.Timeout:
            print(f"\n✗ Request timed out waiting for {language} translations")
            return None
        except Exception as e:
            print(f"\n✗ Error getting translations: {str(e)}")
            return None

def main():
    try:
        print("=== Starting Translation Test ===")
        print("\nGetting function URLs from terraform output...")
        urls = get_function_urls()
        print("Function URLs:")
        for name, url in urls.items():
            print(f"{name}: {url}")
        
        tester = TranslationTester(urls)
        meeting_code = "TEST01"
        
        print("\n=== Setting up Test Meeting ===")
        print("Joining meeting as listeners...")
        tester.join_meeting(meeting_code, "ko")
        tester.join_meeting(meeting_code, "es")
        
        # Only wait if showing logs
        if SHOW_LOGS:
            print("\nWaiting for pub/sub setup...")
            time.sleep(5)
        
        print("\nGetting initial state...")
        check_logs(0)
        
        # Send first audio file
        print("\n=== Testing first audio file ===")
        response = tester.send_audio(meeting_code, "hike.wav")
        if response and response.get('success'):
            check_logs(10)  # Wait 10 seconds then check logs
            
            print("\nChecking translations after first audio...")
            for lang in ["ko", "es"]:
                tester.get_translations(meeting_code, lang)
                if SHOW_LOGS:
                    time.sleep(1)
        
        # Join as French listener
        print("\n=== Adding French listener ===")
        tester.join_meeting(meeting_code, "fr")
        if SHOW_LOGS:
            time.sleep(2)
        
        # Send second audio file
        print("\n=== Testing second audio file ===")
        response = tester.send_audio(meeting_code, "hungry.wav")
        if response and response.get('success'):
            check_logs(10)  # Wait 10 seconds then check logs
            
            print("\nChecking translations after second audio...")
            for lang in ["ko", "es", "fr"]:
                tester.get_translations(meeting_code, lang)
                if SHOW_LOGS:
                    time.sleep(1)
        
        # Test leaving the meeting
        print("\n=== Testing Leave Meeting ===")
        print("Having Korean and Spanish listeners leave...")
        tester.leave_meeting(meeting_code, "ko")
        tester.leave_meeting(meeting_code, "es")
        if SHOW_LOGS:
            time.sleep(2)
        
        # Final log check
        print("\n=== Final log check ===")
        check_logs(5)
        
        # Clean exit - have remaining listeners leave
        print("\n=== Clean Exit ===")
        tester.leave_meeting(meeting_code, "fr")
        tester.leave_meeting(meeting_code, "en-US")  # Speaker leaves
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        print("\nMake sure you have:")
        print("1. Run 'terraform init' and 'terraform apply'")
        print("2. Have the WAV files (hike.wav and hungry.wav)")
        print("3. Have proper permissions set up")
        raise

if __name__ == "__main__":
    main()
