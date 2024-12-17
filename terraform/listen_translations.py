# File: listen_translations.py
import sys
import time
import json
import requests
import subprocess
from datetime import datetime

def get_function_urls():
    """Get the Cloud Function URLs from Terraform outputs."""
    urls = {}
    for function in ['join_meeting_url', 'get_translations_url']:
        process = subprocess.Popen(
            f'terraform output -raw {function}',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = process.communicate()
        if not stdout:
            raise ValueError(f"Could not get URL for {function}")
        urls[function] = stdout.decode().strip()
    return urls

class TranslationListener:
    def __init__(self, meeting_id, language):
        self.meeting_id = meeting_id
        self.language = language
        self.debug = True  # Enable/disable debug output
        
        # Get function URLs
        urls = get_function_urls()
        self.join_url = urls['join_meeting_url']
        self.translations_url = urls['get_translations_url']
        
        # Join as listener
        response = requests.post(
            self.join_url,
            json={
                'meetingCode': meeting_id,
                'targetLanguage': language
            }
        )
        
        if response.status_code != 200:
            raise Exception("Failed to join meeting")
        
        data = response.json()
        if not data.get('success'):
            raise Exception(data.get('error', 'Unknown error joining meeting'))
        
        self.client_id = data['clientId']
        print(f"\n=== Joined Translation Session ===")
        print(f"Meeting ID: {meeting_id}")
        print(f"Language: {language}")
        print(f"Client ID: {self.client_id}")
        print("\nWaiting for translations...")

    def debug_print(self, *args, **kwargs):
        """Print debug information if debug mode is enabled."""
        if self.debug:
            print("DEBUG:", *args, **kwargs)

    def process_translation(self, translation):
        """Process and print a single translation."""
        try:
            self.debug_print(f"Processing translation: {json.dumps(translation, indent=2)}")
            
            # Get the translation text
            text = translation.get('data', '').decode('utf-8') if isinstance(translation.get('data'), bytes) else translation.get('data', '')
            if not text:
                text = translation.get('translatedText', '')
            
            # Try to decode if it's JSON
            try:
                json_data = json.loads(text)
                if isinstance(json_data, dict):
                    text = json_data.get('translatedText', text)
            except:
                pass
            
            # Get timestamp
            timestamp = translation.get('timestamp')
            if not timestamp:
                timestamp = translation.get('publish_time')
            
            time_str = datetime.fromtimestamp(float(timestamp)).strftime('%H:%M:%S') if timestamp else 'N/A'
            
            # Print the translation
            print(f"\n[{time_str}] {text}")
            
        except Exception as e:
            self.debug_print(f"Error processing translation: {str(e)}")

    def listen(self):
        """Continuously listen for translations."""
        try:
            last_check = time.time()
            
            while True:
                try:
                    self.debug_print("\nChecking for translations...")
                    self.debug_print(f"URL: {self.translations_url}")
                    self.debug_print(f"Params: meetingCode={self.meeting_id}, language={self.language}, clientId={self.client_id}")
                    
                    response = requests.get(
                        self.translations_url,
                        params={
                            'meetingCode': self.meeting_id,
                            'targetLanguage': self.language,
                            'clientId': self.client_id
                        },
                        timeout=20
                    )
                    
                    self.debug_print(f"Response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        data = response.json()
                        self.debug_print(f"Response data: {json.dumps(data, indent=2)}")
                        
                        if data.get('success'):
                            translations = data.get('translations', [])
                            self.debug_print(f"Found {len(translations)} translations")
                            
                            for translation in translations:
                                self.process_translation(translation)
                        else:
                            self.debug_print("Response marked as not successful")
                            
                    current_time = time.time()
                    elapsed = current_time - last_check
                    if elapsed < 1:
                        time.sleep(1 - elapsed)
                    last_check = time.time()
                    
                except requests.Timeout:
                    self.debug_print("Request timed out, retrying...")
                    continue
                except requests.RequestException as e:
                    self.debug_print(f"Request error: {str(e)}")
                    time.sleep(5)  # Longer delay on error
                except Exception as e:
                    self.debug_print(f"Unexpected error: {str(e)}")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            print("\nStopping listener...")

def main():
    if len(sys.argv) != 3:
        print("Usage: python listen_translations.py <meeting_id> <language>")
        print("Example: python listen_translations.py ABC123 es")
        sys.exit(1)
    
    meeting_id = sys.argv[1].upper()
    language = sys.argv[2].lower()
    
    listener = TranslationListener(meeting_id, language)
    listener.listen()

if __name__ == "__main__":
    main()