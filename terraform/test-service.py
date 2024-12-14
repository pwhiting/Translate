import os
import json
import time
import subprocess
import requests
import base64
from datetime import datetime

def run_command(cmd):
    """Run a shell command and return output."""
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    return stdout.decode().strip(), stderr.decode()

def get_function_urls():
    """Get the Cloud Function URLs from Terraform outputs."""
    urls = {}
    for function in ['join_meeting_url', 'process_audio_url', 'get_translations_url']:
        stdout, _ = run_command(f'terraform output -raw {function}')
        if not stdout:
            raise ValueError(f"Could not get URL for {function} from terraform output")
        urls[function] = stdout.strip()
    return urls

def get_logs(limit=150):
    """Get Cloud Function logs."""
    cmd = f'gcloud functions logs read --limit {limit}'
    stdout, stderr = run_command(cmd)
    print("\nCloud Function Logs:")
    print(stdout)
    if stderr:
        print("Errors:", stderr)

class TranslationTester:
    def __init__(self, urls):
        self.urls = urls
        self.participants = {}
        self.last_sequences = {}
    
    def join_meeting(self, meeting_code, language):
        """Join a meeting with specified language."""
        response = requests.post(
            self.urls['join_meeting_url'],
            json={
                'meetingCode': meeting_code,
                'targetLanguage': language
            }
        )
        data = response.json()
        if data.get('success'):
            participant_id = data['participantId']
            self.participants[language] = participant_id
            self.last_sequences[language] = None
            print(f"Joined meeting {meeting_code} as {participant_id} (Language: {language})")
        else:
            print(f"Failed to join meeting: {data.get('error', 'Unknown error')}")
        return data
    
    def send_audio(self, meeting_code, audio_file):
        """Send audio file for translation."""
        wav_file = audio_file
        if audio_file.endswith('.base64'):
            wav_file = audio_file.replace('.base64', '.wav')
        
        try:
            with open(wav_file, 'rb') as f:
                audio_data = base64.b64encode(f.read()).decode('utf-8')
            
            print(f"\nSending audio file: {wav_file} (encoded length: {len(audio_data)})")
            
            response = requests.post(
                self.urls['process_audio_url'],
                json={
                    'meetingCode': meeting_code,
                    'sourceLanguage': 'en-US',
                    'audioData': audio_data
                }
            )
            
            data = response.json()
            if data.get('success'):
                print(f"Successfully processed audio: {wav_file}")
                print(f"Transcription: {data.get('transcription', '')}")
                if data.get('translations_generated'):
                    print(f"Generated {data['translations_generated']} translations")
            else:
                print(f"Error processing audio: {data.get('error', 'Unknown error')}")
            
            return data
            
        except FileNotFoundError:
            print(f"Error: Could not find audio file {wav_file}")
            print("Make sure you have the WAV files (hike.wav and hungry.wav)")
            raise
        except Exception as e:
            print(f"Error processing audio file: {str(e)}")
            raise
    
    def get_translations(self, meeting_code, language):
        """Get translations for a specific language."""
        params = {
            'meetingCode': meeting_code,
            'targetLanguage': language
        }
        
        if self.last_sequences[language] is not None:
            params['sequence'] = self.last_sequences[language]
        
        try:
            print(f"\nGetting translations for {language}...")
            if self.last_sequences[language] is None:
                print("Initial registration request")
            else:
                print(f"Requesting content after sequence {self.last_sequences[language]}")
                
            response = requests.get(
                self.urls['get_translations_url'],
                params=params,
                timeout=20
            )
            
            if response.status_code != 200:
                print(f"Error: Server returned status code {response.status_code}")
                print(f"Response: {response.text}")
                return None
                
            data = response.json()
            
            if not data.get('success'):
                print(f"Error: {data.get('error', 'Unknown error')}")
                return data
            
            if data.get('translations'):
                translation = data['translations'][0]  # Should only be one
                
                # Always store sequence, even for empty responses
                if translation.get('sequence') is not None:
                    self.last_sequences[language] = translation['sequence']
                    print(f"Updated sequence for {language} to {translation['sequence']}")
                
                if translation.get('empty'):
                    print(f"No new content for {language}")
                else:
                    print(f"Received translation for {language}:")
                    print(f"Text: {translation['translatedText']}")
                    print(f"Sequence: {translation['sequence']}")
            
            return data
            
        except requests.Timeout:
            print(f"Request timed out waiting for translations for {language}")
            return None
        except Exception as e:
            print(f"Error getting translations: {str(e)}")
            return None

def main():
    try:
        # Get function URLs from terraform output
        print("Getting function URLs from terraform output...")
        urls = get_function_urls()
        print("Function URLs:")
        for name, url in urls.items():
            print(f"{name}: {url}")
        
        # Initialize tester
        tester = TranslationTester(urls)
        meeting_code = "TEST01"
        
        # Join meeting as Korean and Spanish listeners
        print("\nJoining meeting as listeners...")
        tester.join_meeting(meeting_code, "ko")
        tester.join_meeting(meeting_code, "es")
        
        # Initial registration requests - store returned sequences
        print("\nPerforming initial registration...")
        for lang in ["ko", "es"]:
            response = tester.get_translations(meeting_code, lang)
            print(f"Initial sequence for {lang}: {tester.last_sequences[lang]}")
            time.sleep(1)
        
        # Send first audio file
        print("\nSending first audio file...")
        response = tester.send_audio(meeting_code, "hike.wav")
        if response and response.get('success'):
       #     print("Waiting for translations to process...")
       #     time.sleep(5)
            
            print("\nGetting translations after first audio...")
            print("Using sequences:", tester.last_sequences)
            for lang in ["ko", "es"]:
                tester.get_translations(meeting_code, lang)
                time.sleep(1)
        
        # Join as French listener
        print("\nJoining meeting as French listener...")
        tester.join_meeting(meeting_code, "fr")
        response = tester.get_translations(meeting_code, "fr")  # Initial registration
        print(f"Initial sequence for fr: {tester.last_sequences['fr']}")
        
        # Send second audio file
        print("\nSending second audio file...")
        response = tester.send_audio(meeting_code, "hungry.wav")
        if response and response.get('success'):
    #        print("Waiting for translations to process...")
            time.sleep(1)
            
            print("\nGetting translations after second audio...")
            print("Using sequences:", tester.last_sequences)
            for lang in ["ko", "es", "fr"]:
                tester.get_translations(meeting_code, lang)
                time.sleep(1)
        
        # Final delay before getting logs
    #    time.sleep(3)
    #    get_logs()
        
    except Exception as e:
        print(f"\nError: {str(e)}")
        print("\nMake sure you have:")
        print("1. Run 'terraform init' and 'terraform apply'")
        print("2. Have the WAV files (hike.wav and hungry.wav)")
        print("3. Have proper permissions set up")
        raise

if __name__ == "__main__":
    main()
