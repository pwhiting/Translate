import os
import sys
import time
import random
import string
import wave
import requests
import base64
import subprocess
from pydub import AudioSegment
from datetime import datetime

def generate_meeting_id():
    """Generate a random 6-character meeting ID."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(6))

def get_function_urls():
    """Get the Cloud Function URLs from Terraform outputs."""
    urls = {}
    for function in ['join_meeting_url', 'process_audio_url']:
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

class MP3Streamer:
    def __init__(self, mp3_file, meeting_id=None):
        self.mp3_file = mp3_file
        self.meeting_id = meeting_id or generate_meeting_id()
        self.chunk_duration = 2500  # 2.5 seconds in milliseconds
        self.debug = True  # Enable debug output
        
        # Get function URLs
        urls = get_function_urls()
        self.join_url = urls['join_meeting_url']
        self.process_url = urls['process_audio_url']
        
        # Join as speaker
        self.client_id = self.join_meeting()
        
        print(f"\n=== Started MP3 Streaming Session ===")
        print(f"Meeting ID: {self.meeting_id}")
        print(f"File: {self.mp3_file}")
        print(f"Client ID: {self.client_id}")
        print(f"Chunk Duration: {self.chunk_duration}ms")
        print(f"URLs:")
        print(f"  Join: {self.join_url}")
        print(f"  Process: {self.process_url}")
        
    def debug_print(self, *args, **kwargs):
        """Print debug information if debug mode is enabled."""
        if self.debug:
            print("DEBUG:", *args, **kwargs)
            
    def join_meeting(self):
        """Join the meeting as a speaker."""
        self.debug_print("Joining meeting...")
        response = requests.post(
            self.join_url,
            json={
                'meetingCode': self.meeting_id,
                'targetLanguage': 'en-US'
            }
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to join meeting: HTTP {response.status_code}")
            
        data = response.json()
        if not data.get('success'):
            raise Exception(data.get('error', 'Unknown error joining meeting'))
            
        self.debug_print(f"Successfully joined meeting")
        return data['clientId']

    def process_chunk(self, chunk_audio, chunk_number):
        """Convert audio chunk to WAV and send to service."""
        self.debug_print(f"\nProcessing chunk {chunk_number}:")
        
        # Export as WAV with correct parameters
        self.debug_print("Converting chunk to WAV format...")
        chunk_audio = chunk_audio.set_frame_rate(16000)  # Required for Google Speech-to-Text
        chunk_audio = chunk_audio.set_channels(1)        # Mono
        chunk_audio = chunk_audio.set_sample_width(2)    # 16-bit
        
        # Export to temporary WAV file
        temp_filename = f"temp_{self.meeting_id}_{chunk_number}.wav"
        self.debug_print(f"Exporting to temporary file: {temp_filename}")
        chunk_audio.export(temp_filename, format="wav")
        
        try:
            # Read and encode the WAV file
            self.debug_print("Reading and encoding WAV file...")
            with open(temp_filename, 'rb') as f:
                audio_data = base64.b64encode(f.read()).decode('utf-8')
            
            self.debug_print("Preparing API request...")
            request_data = {
                'meetingCode': self.meeting_id,
                'sourceLanguage': 'en-US',
                'audioData': audio_data,
                'clientId': self.client_id
            }
            
            self.debug_print("Sending chunk to processing service...")
            response = requests.post(
                self.process_url,
                json=request_data
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    self.debug_print(f"✓ Chunk {chunk_number} processed successfully")
                    self.debug_print(f"  Message ID: {data.get('messageId')}")
                    self.debug_print(f"  Audio Size: {data.get('audioSize')} bytes")
                    self.debug_print(f"  Timestamp: {data.get('timestamp')}")
                else:
                    self.debug_print(f"✗ Error processing chunk {chunk_number}: {data.get('error')}")
            else:
                self.debug_print(f"✗ HTTP Error {response.status_code} for chunk {chunk_number}")
                
        except Exception as e:
            self.debug_print(f"✗ Error processing chunk {chunk_number}: {str(e)}")
        finally:
            # Clean up temporary file
            try:
                os.remove(temp_filename)
                self.debug_print(f"Cleaned up temporary file: {temp_filename}")
            except:
                self.debug_print(f"Failed to cleanup temporary file: {temp_filename}")

    def stream(self):
        """Stream the MP3 file in chunks at normal playback speed."""
        try:
            self.debug_print("Loading MP3 file...")
            audio = AudioSegment.from_mp3(self.mp3_file)
            duration = len(audio)
            
            self.debug_print(f"File loaded successfully:")
            self.debug_print(f"  Duration: {duration}ms")
            self.debug_print(f"  Channels: {audio.channels}")
            self.debug_print(f"  Sample Width: {audio.sample_width} bytes")
            self.debug_print(f"  Frame Rate: {audio.frame_rate} Hz")
            
            # Process chunks at normal playback speed
            chunk_number = 0
            start = 0
            
            self.debug_print(f"\nStarting chunk processing...")
            while start < duration:
                chunk_start = time.time()
                chunk_number += 1
                
                # Extract chunk
                end = min(start + self.chunk_duration, duration)
                chunk = audio[start:end]
                
                self.debug_print(f"\n=== Processing Chunk {chunk_number} ===")
                self.debug_print(f"Time Range: {start}ms to {end}ms")
                self.debug_print(f"Duration: {len(chunk)}ms")
                
                # Process chunk
                self.process_chunk(chunk, chunk_number)
                
                # Calculate sleep time for real-time playback
                processing_time = time.time() - chunk_start
                sleep_time = (self.chunk_duration / 1000.0) - processing_time
                
                if sleep_time > 0:
                    self.debug_print(f"Waiting {sleep_time:.2f}s for real-time playback...")
                    time.sleep(sleep_time)
                
                start = end
                
            self.debug_print(f"\n✓ Processing complete")
            self.debug_print(f"Total chunks processed: {chunk_number}")
            
        except Exception as e:
            self.debug_print(f"✗ Error streaming MP3: {str(e)}")
            raise

def main():
    if len(sys.argv) != 2:
        print("Usage: python stream_mp3.py <mp3_file>")
        print("Example: python stream_mp3.py speech.mp3")
        sys.exit(1)
        
    mp3_file = sys.argv[1]
    if not os.path.exists(mp3_file):
        print(f"Error: File {mp3_file} not found")
        sys.exit(1)
        
    try:
        streamer = MP3Streamer(mp3_file)
        streamer.stream()
    except Exception as e:
        print(f"\nError: {str(e)}")
        print("\nMake sure you have:")
        print("1. Run 'terraform init' and 'terraform apply'")
        print("2. Have the MP3 file in the correct location")
        print("3. Have proper permissions set up")
        sys.exit(1)

if __name__ == "__main__":
    main()