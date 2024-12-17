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
        urls[function] = stdout.strip().decode('utf-8')
    return urls

def process_translation(translation):
    """Extract translated text from translation data handling multiple formats."""
    # Try getting from data field first
    text = translation.get('data', '')
    
    # Handle bytes if necessary
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    
    # If no text found in data, try translatedText
    if not text:
        text = translation.get('translatedText', '')
    
    # Try parsing as JSON if possible
    try:
        json_data = json.loads(text)
        if isinstance(json_data, dict):
            text = json_data.get('translatedText', text)
    except json.JSONDecodeError:
        pass
    
    return text.strip()

class TranslationListener:
    def __init__(self, meeting_id, language):
        # Get function URLs
        urls = get_function_urls()
        
        # Join meeting
        response = requests.post(
            urls['join_meeting_url'],
            json={
                'meetingCode': meeting_id,
                'targetLanguage': language
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to join meeting: HTTP {response.status_code}")
        
        data = response.json()
        if not data.get('success'):
            raise Exception(data.get('error', 'Unknown error joining meeting'))
        
        self.client_id = data['clientId']
        self.meeting_id = meeting_id
        self.language = language
        self.translations_url = urls['get_translations_url']
        
        print(f"\n=== Translation Session Started ===")
        print(f"Meeting ID: {meeting_id}")
        print(f"Language: {language}")
        print("\nListening for translations...")

    def listen(self):
        """Listen for and display translations."""
        last_check = time.time()
        
        try:
            while True:
                try:
                    # Get translations
                    response = requests.get(
                        self.translations_url,
                        params={
                            'meetingCode': self.meeting_id,
                            'targetLanguage': self.language,
                            'clientId': self.client_id
                        },
                        timeout=20
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('success'):
                            translations = data.get('translations', [])
                            
                            # Process each translation
                            for translation in translations:
                                text = process_translation(translation)
                                if text:
                                    # Get timestamp if available
                                    timestamp = translation.get('timestamp') or translation.get('publish_time')
                                    time_str = ''
                                    if timestamp:
                                        time_str = f"[{datetime.fromtimestamp(float(timestamp)).strftime('%H:%M:%S')}] "
                                    
                                    print(f"\n{time_str}{text}")
                    
                    # Rate limiting
                    current_time = time.time()
                    elapsed = current_time - last_check
                    if elapsed < 1:
                        time.sleep(1 - elapsed)
                    last_check = time.time()
                    
                except requests.Timeout:
                    continue
                except requests.RequestException as e:
                    print(f"\nConnection error: {str(e)}")
                    time.sleep(5)
                except Exception as e:
                    print(f"\nUnexpected error: {str(e)}")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            print("\nStopping translation listener...")

def main():
    if len(sys.argv) != 3:
        print("Usage: python clean_listen.py <meeting_id> <language>")
        print("Example: python clean_listen.py ABC123 es")
        sys.exit(1)
    
    meeting_id = sys.argv[1].upper()
    language = sys.argv[2].lower()
    
    try:
        listener = TranslationListener(meeting_id, language)
        listener.listen()
    except Exception as e:
        print(f"\nError: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()