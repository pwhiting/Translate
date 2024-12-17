import os
import json
from google.cloud import speech_v1
from google.cloud import pubsub_v1
from google.api_core import retry, exceptions
import logging
import time
from flask import Flask, request
# Initialize Flask app
app = Flask(__name__)
# Configure root logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
class StreamManager:
    def __init__(self): 
        self.project_id = os.getenv('PROJECT_ID')
        self.logger = logging.getLogger('stream-manager')
        retry_count = 5
        
        for attempt in range(retry_count):
            try:
                self.logger.info(f"=== Initializing StreamManager (Attempt {attempt + 1}/{retry_count}) ===")
                self.logger.info(f"Project ID: {self.project_id}")
                
                # Initialize clients
                self.logger.info("Initializing service clients...")
                
                # Create clients with retry
                retry_config = retry.Retry(
                    initial=1.0,
                    maximum=60.0,
                    multiplier=2.0,
                    predicate=retry.if_exception_type(
                        exceptions.DeadlineExceeded,
                        exceptions.ServiceUnavailable,
                        exceptions.InternalServerError,
                        exceptions.ResourceExhausted
                    )
                )
                
                self.speech_client = speech_v1.SpeechClient()
                self.publisher = pubsub_v1.PublisherClient()
                self.subscriber = pubsub_v1.SubscriberClient()
                
                # Set up paths
                self.subscription_path = self.subscriber.subscription_path(
                    self.project_id, 
                    'audio-fragments-sub'
                )
                self.translation_topic_path = self.publisher.topic_path(
                    self.project_id,
                    'translation-requests'
                )
                
                # Start subscription right away
                self.streaming_pull_future = self.start_subscriber()
                
                self.logger.info("Service clients initialized successfully")
                self.logger.info(f"Using subscription: {self.subscription_path}")
                self.logger.info(f"Publishing to topic: {self.translation_topic_path}")
                
                # If we got here, initialization was successful
                return
                
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed: {str(e)}", exc_info=True)
                if attempt == retry_count - 1:
                    raise
                sleep_time = min(2 ** attempt, 60)
                self.logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)


    def process_audio(self, audio_data, meeting_code, source_language):
        """Process audio chunk using Speech-to-Text streaming API."""
        try:
            self.logger.info(f"=== Processing audio for meeting {meeting_code} ===")
            self.logger.info(f"Audio size: {len(audio_data)} bytes")
            self.logger.info(f"Source language: {source_language}")
            
            # Create recognition config
            config = speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=source_language,
                enable_automatic_punctuation=True,
                enable_word_time_offsets=True  # Enable timing info
            )
            
            # Create streaming config
            streaming_config = speech_v1.StreamingRecognitionConfig(
                config=config,
                interim_results=False
            )
            
            # Create streaming requests
            requests = [speech_v1.StreamingRecognizeRequest(audio_content=audio_data)]
            
            self.logger.info("Sending request to Speech-to-Text streaming API...")
            responses = self.speech_client.streaming_recognize(
                config=streaming_config,
                requests=iter(requests)
            )
            
            # Process streaming responses and sort by start time
            results_with_timing = []
            
            for response in responses:
                for result in response.results:
                    if not result.is_final:
                        continue
                    
                    transcript = result.alternatives[0].transcript
                    confidence = result.alternatives[0].confidence
                    
                    if not transcript.strip():
                        continue
                    
                    # Get timing information
                    start_time = None
                    if result.alternatives[0].words:
                        # Get the start time of the first word
                        start_time = result.alternatives[0].words[0].start_time.total_seconds()
                    else:
                        # If no word timing, use current time
                        start_time = time.time()
                    
                    results_with_timing.append({
                        'transcript': transcript,
                        'confidence': confidence,
                        'start_time': start_time
                    })
            
            # Sort results by start time
            sorted_results = sorted(results_with_timing, key=lambda x: x['start_time'])
            
            # Publish sorted results
            for result in sorted_results:
                self.logger.info(
                    f"Publishing transcript:\n"
                    f"- Start time: {result['start_time']:.3f}s\n"
                    f"- Length: {len(result['transcript'])} chars\n"
                    f"- Confidence: {result['confidence']:.2f}\n"
                    f"- Text: {result['transcript']}"
                )
                
                message_data = {
                    'meetingCode': meeting_code,
                    'sourceLanguage': source_language,
                    'text': result['transcript'],
                    'confidence': result['confidence'],
                    'timestamp': result['start_time'],
                    'publish_time': time.time()
                }
                
                future = self.publisher.publish(
                    self.translation_topic_path,
                    json.dumps(message_data).encode('utf-8')
                )
                message_id = future.result()
                self.logger.info(f"Published transcription with ID: {message_id}")
            
            # Return combined transcript
            if sorted_results:
                return ' '.join(r['transcript'] for r in sorted_results)
            return None
            
        except Exception as e:
            self.logger.error(f"Error processing audio: {str(e)}", exc_info=True)
            return None
    
    def process_audio2(self, audio_data, meeting_code, source_language):
        """Process audio chunk using Speech-to-Text streaming API."""
        try:
            self.logger.info(f"=== Processing audio for meeting {meeting_code} ===")
            self.logger.info(f"Audio size: {len(audio_data)} bytes")
            self.logger.info(f"Source language: {source_language}")
            
            # Create streaming config
            config = speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=source_language,
                enable_automatic_punctuation=True
            )
            
            streaming_config = speech_v1.StreamingRecognitionConfig(
                config=config,
                interim_results=False  # Only get final results
            )
            
            # Create streaming request
            requests = [
                speech_v1.StreamingRecognizeRequest(
                    streaming_config=streaming_config
                ),
                speech_v1.StreamingRecognizeRequest(audio_content=audio_data)
            ]
            
            self.logger.info("Sending request to Speech-to-Text streaming API...")
            responses = self.speech_client.streaming_recognize(requests=iter(requests))
            #responses = self.speech_client.streaming_recognize(requests)
            
            # Process streaming responses
            for response in responses:
                if not response.results:
                    continue
                    
                result = response.results[0]
                if not result.is_final:
                    continue
                    
                transcript = result.alternatives[0].transcript
                confidence = result.alternatives[0].confidence
                
                if transcript.strip():
                    self.logger.info(
                        f"Transcription successful:\n"
                        f"- Length: {len(transcript)} chars\n"
                        f"- Confidence: {confidence:.2f}\n"
                        f"- Text: {transcript}"
                    )
                    
                    # Publish for translation
                    message_data = {
                        'meetingCode': meeting_code,
                        'sourceLanguage': source_language,
                        'text': transcript,
                        'confidence': confidence,
                        'timestamp': time.time()
                    }
                    
                    self.logger.info("Publishing transcription to translation topic...")
                    future = self.publisher.publish(
                        self.translation_topic_path,
                        json.dumps(message_data).encode('utf-8')
                    )
                    message_id = future.result()
                    self.logger.info(f"Published transcription with ID: {message_id}")
                    
                    return transcript
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error processing audio: {str(e)}", exc_info=True)
            return None
    def process_message(self, message):
        """Process incoming Pub/Sub message containing audio data."""
        start_time = time.time()
        
        try:
            self.logger.info("=== Received new message ===")
            self.logger.info(f"Message ID: {message.message_id}")
            self.logger.info(f"Publish time: {message.publish_time}")
            self.logger.info(f"Attributes: {message.attributes}")
            self.logger.info(f"Data size: {len(message.data)} bytes")
            
            meeting_code = message.attributes.get('meetingCode')
            source_language = message.attributes.get('sourceLanguage')
            
            self.logger.info(f"Processing message for meeting {meeting_code} in {source_language}")
            
            if not meeting_code or not source_language:
                self.logger.error(f"Missing required attributes. Found: {message.attributes}")
                message.nack()
                return
            
            # Process audio using streaming recognition
            transcript = self.process_audio(
                message.data,
                meeting_code,
                source_language
            )
            
            if transcript is not None:
                self.logger.info(f"Successfully processed audio. Transcript length: {len(transcript)}")
                message.ack()
            else:
                self.logger.error("Failed to process audio - no transcript generated")
                message.nack()
            
            processing_time = time.time() - start_time
            self.logger.info(f"Message processing completed in {processing_time:.2f}s")
            
        except Exception as e:
            self.logger.error(f"Error processing message: {str(e)}", exc_info=True)
            message.nack()
    def start_subscriber(self):
        """Start the subscription to audio messages."""
        try:
            self.logger.info("Starting message subscription...")
            streaming_pull_future = self.subscriber.subscribe(
                self.subscription_path,
                callback=self.process_message
            )
            self.logger.info("Message subscription started successfully")
            return streaming_pull_future
        except Exception as e:
            self.logger.error(f"Failed to start subscription: {str(e)}")
            raise
# Create service instance
manager = StreamManager()
@app.route('/health')
def health_check():
    """Health check endpoint."""
    return {'status': 'healthy'}, 200
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
