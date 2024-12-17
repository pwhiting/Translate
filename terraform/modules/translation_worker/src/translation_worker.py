import os
import json
import base64
from google.cloud import speech_v1
from google.cloud import translate_v2
from google.cloud import pubsub_v1
from google.cloud import firestore
import logging
import time
from concurrent.futures import TimeoutError
from flask import Flask, request
from datetime import datetime
from typing import Dict, List
import heapq
from dataclasses import dataclass, field
from threading import Lock
app = Flask(__name__)
# Configure root logger first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('translation-worker')
@dataclass(order=True)
class PendingMessage:
    timestamp: float
    message: dict = field(compare=False)
    message_id: str = field(compare=False)
class MessageBuffer:
    def __init__(self, buffer_time=1.0):
        self.buffer: Dict[str, List[PendingMessage]] = {}  # meeting_code -> messages
        self.buffer_time = buffer_time  # Time to buffer messages in seconds
        self.lock = Lock()
    def add_message(self, meeting_code: str, message_data: dict, message_id: str):
        with self.lock:
            if meeting_code not in self.buffer:
                self.buffer[meeting_code] = []
            
            timestamp = float(message_data.get('timestamp', 0))
            heapq.heappush(
                self.buffer[meeting_code],
                PendingMessage(timestamp, message_data, message_id)
            )
    def get_ready_messages(self, current_time: float) -> Dict[str, List[PendingMessage]]:
        ready_messages = {}
        with self.lock:
            for meeting_code, messages in list(self.buffer.items()):
                if not messages:
                    continue
                # Get all messages that are ready for processing
                ready = []
                while messages and (current_time - messages[0].timestamp) >= self.buffer_time:
                    ready.append(heapq.heappop(messages))
                if ready:
                    ready_messages[meeting_code] = ready
        return ready_messages
class TranslationWorker:
    def __init__(self):
        self.project_id = os.getenv('PROJECT_ID')
        self.translation_sub = os.getenv('TRANSLATION_SUB', 'translation-requests-sub')
        self.streaming_pull_future = None
        self.message_buffer = MessageBuffer(buffer_time=1.0)  # 1 second buffer
        
        try:
            logger.info("=== Initializing Translation Worker ===")
            logger.info(f"Project ID: {self.project_id}")
            logger.info(f"Subscription: {self.translation_sub}")
            
            # Initialize clients
            self.speech_client = speech_v1.SpeechClient()
            self.translate_client = translate_v2.Client()
            self.publisher = pubsub_v1.PublisherClient()
            self.subscriber = pubsub_v1.SubscriberClient()
            self.db = firestore.Client()
            
            # Set up subscription path
            self.translation_subscription_path = self.subscriber.subscription_path(
                self.project_id, 
                self.translation_sub
            )
            
            # Start subscription immediately
            self.start_subscriber()
            # Start message processing thread
            self._start_message_processor()
            
            logger.info("Translation Worker initialization complete")
            
        except Exception as e:
            logger.error(f"✗ Initialization error: {str(e)}", exc_info=True)
            raise
    def start_subscriber(self):
        """Start the subscription with enhanced monitoring."""
        try:
            logger.info("\n=== Starting Translation Subscription ===")
            logger.info(f"Subscription Path: {self.translation_subscription_path}")
            
            def callback(message):
                """Handle incoming messages."""
                try:
                    logger.debug(f"Raw message data: {message.data.decode('utf-8')}")
                    self.process_message(message)
                except Exception as e:
                    logger.error(f"Error in message callback: {str(e)}")
                    message.nack()
            
            # Configure flow control
            flow_control = pubsub_v1.types.FlowControl(
                max_messages=1,
                max_bytes=10 * 1024 * 1024
            )
            
            logger.info("Starting message subscription...")
            
            # Start subscription with flow control
            self.streaming_pull_future = self.subscriber.subscribe(
                self.translation_subscription_path,
                callback=callback,
                flow_control=flow_control
            )
            
            logger.info("✓ Subscription started successfully")
            return self.streaming_pull_future
            
        except Exception as e:
            logger.error(f"✗ Failed to start subscription: {str(e)}", exc_info=True)
            raise
    def _start_message_processor(self):
        """Start background thread to process buffered messages."""
        import threading
        
        def process_loop():
            while True:
                try:
                    current_time = time.time()
                    ready_messages = self.message_buffer.get_ready_messages(current_time)
                    
                    for meeting_code, messages in ready_messages.items():
                        for pending_msg in messages:
                            self._process_buffered_message(
                                meeting_code,
                                pending_msg.message,
                                pending_msg.message_id
                            )
                    
                    time.sleep(0.1)  # Small sleep to prevent CPU spinning
                except Exception as e:
                    logger.error(f"Error in message processor: {str(e)}")
                    time.sleep(1)  # Longer sleep on error
        thread = threading.Thread(target=process_loop, daemon=True)
        thread.start()
    def _process_buffered_message(self, meeting_code: str, message_data: dict, message_id: str):
        """Process a single buffered message."""
        try:
            source_language = message_data.get('sourceLanguage')
            text = message_data.get('text')
            timestamp = message_data.get('timestamp')
            
            logger.info(f"\n=== Processing Buffered Message ===")
            logger.info(f"Meeting: {meeting_code}")
            logger.info(f"Message ID: {message_id}")
            logger.info(f"Timestamp: {timestamp}")
            logger.info(f"Text: {text}")
            
            # Get target languages and translate
            target_languages = self.get_meeting_languages(meeting_code)
            
            for target_lang in target_languages:
                self.translate_and_publish(
                    text,
                    source_language,
                    target_lang,
                    meeting_code,
                    timestamp
                )
                
        except Exception as e:
            logger.error(f"Error processing buffered message: {str(e)}")
    def get_meeting_languages(self, meeting_code):
        """Get target languages for a meeting."""
        try:
            meeting_ref = self.db.collection('meetings').document(meeting_code)
            meeting = meeting_ref.get()
            
            if not meeting.exists:
                logger.warning(f"Meeting {meeting_code} not found")
                return []
                
            languages = meeting.to_dict().get('targetLanguages', [])
            logger.debug(f"Found languages for {meeting_code}: {languages}")
            return languages
            
        except Exception as e:
            logger.error(f"Error fetching meeting languages: {str(e)}")
            return []
    def process_message(self, message):
        """Handle incoming message by adding to buffer."""
        try:
            data = json.loads(message.data.decode('utf-8'))
            meeting_code = data.get('meetingCode')
            
            if not meeting_code:
                logger.error("Missing meeting code in message")
                message.nack()
                return
            
            # Add to buffer
            self.message_buffer.add_message(
                meeting_code,
                data,
                message.message_id
            )
            
            message.ack()
            
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
            message.nack()
    def translate_and_publish(self, text, source_language, target_lang, meeting_code, original_timestamp):
        """Translate text and publish to language-specific topic."""
        source_lang = source_language.split('-')[0]
        
        try:
            if target_lang == source_lang:
                translated_text = text
            else:
                translation = self.translate_client.translate(
                    text,
                    target_language=target_lang,
                    source_language=source_lang
                )
                translated_text = translation['translatedText']
            
            # Get or create topic
            topic_id = f"meeting-{meeting_code}-{target_lang}"
            topic_path = self.publisher.topic_path(self.project_id, topic_id)
            
            message_data = {
                'translatedText': translated_text,
                'sourceLanguage': source_language,
                'timestamp': original_timestamp,  # Preserve original timestamp
                'publish_time': time.time()      # Add current publish time
            }
            
            future = self.publisher.publish(
                topic_path,
                json.dumps(message_data).encode('utf-8')
            )
            message_id = future.result()
            
            logger.info(
                f"Published translation:\n"
                f"- Language: {target_lang}\n"
                f"- Message ID: {message_id}\n"
                f"- Original Timestamp: {original_timestamp}\n"
                f"- Text: {translated_text[:100]}..."
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing translation for {target_lang}: {str(e)}")
            return False
# Initialize translation worker at module level
translation_worker = None
def initialize_worker():
    global translation_worker
    if translation_worker is None:
        try:
            translation_worker = TranslationWorker()
            logger.info("Translation worker initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize translation worker: {str(e)}")
            raise
# Initialize on startup
try:
    initialize_worker()
except Exception as e:
    logger.error(f"Failed to initialize application: {str(e)}")
@app.route('/')
def root():
    """Root endpoint for basic health checks."""
    return {'status': 'online'}, 200
@app.route('/health')
def health_check():
    """Health check endpoint."""
    if translation_worker is None:
        return {'status': 'unhealthy', 'error': 'Translation worker not initialized'}, 500
    return {'status': 'healthy'}, 200
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
