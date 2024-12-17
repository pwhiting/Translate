import os
import sys
import time
import random
import string
import pyaudio
import wave
import threading
import requests
import base64
import subprocess
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
class AudioRecorder:
    def __init__(self, meeting_id):
        self.meeting_id = meeting_id
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000  # Required for Google Speech-to-Text
        self.record_seconds = 5  # Record in 5-second chunks
        self.p = pyaudio.PyAudio()
        
        # Get function URLs
        urls = get_function_urls()
        self.join_url = urls['join_meeting_url']
        self.process_url = urls['process_audio_url']
        
        # Join as speaker
        self.client_id = self.join_meeting()
        
        # Initialize recording flag
        self.is_recording = False
        
    def join_meeting(self):
        """Join the meeting as a speaker."""
        response = requests.post(
            self.join_url,
            json={
                'meetingCode': self.meeting_id,
                'targetLanguage': 'en-US'
            }
        )
        if response.status_code != 200:
            raise Exception("Failed to join meeting")
        data = response.json()
        if not data.get('success'):
            raise Exception(data.get('error', 'Unknown error joining meeting'))
        return data['clientId']
    def record_chunk(self):
        """Record a single chunk of audio and send it."""
        stream = self.p.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk
        )
        
        print("\nRecording...")
        frames = []
        
        for _ in range(0, int(self.rate / self.chunk * self.record_seconds)):
            if not self.is_recording:
                break
            data = stream.read(self.chunk)
            frames.append(data)
        
        stream.stop_stream()
        stream.close()
        
        if frames:  # Only process if we have audio data
            # Save to temporary WAV file
            temp_filename = f"temp_{int(time.time())}.wav"
            wf = wave.open(temp_filename, 'wb')
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.p.get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(frames))
            wf.close()
            
            # Send the audio file
            try:
                with open(temp_filename, 'rb') as f:
                    audio_data = base64.b64encode(f.read()).decode('utf-8')
                
                response = requests.post(
                    self.process_url,
                    json={
                        'meetingCode': self.meeting_id,
                        'sourceLanguage': 'en-US',
                        'audioData': audio_data,
                        'clientId': self.client_id
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        print("✓ Audio chunk processed")
                    else:
                        print(f"✗ Error processing audio: {data.get('error')}")
                else:
                    print(f"✗ HTTP Error {response.status_code}")
                
            except Exception as e:
                print(f"✗ Error sending audio: {str(e)}")
            
            # Clean up temporary file
            try:
                os.remove(temp_filename)
            except:
                pass
    def start_recording(self):
        """Start continuous recording."""
        self.is_recording = True
        print(f"\n=== Started Recording ===")
        print(f"Meeting ID: {self.meeting_id}")
        print(f"Client ID: {self.client_id}")
        print("Press Ctrl+C to stop recording")
        
        try:
            while self.is_recording:
                self.record_chunk()
        except KeyboardInterrupt:
            print("\nStopping recording...")
        finally:
            self.is_recording = False
            self.p.terminate()
def main():
    # Generate random meeting ID
    meeting_id = generate_meeting_id()
    print(f"\n=== New Translation Session ===")
    print(f"Meeting ID: {meeting_id}")
    print("Starting audio recorder...")
    
    recorder = AudioRecorder(meeting_id)
    recorder.start_recording()
if __name__ == "__main__":
    main()
