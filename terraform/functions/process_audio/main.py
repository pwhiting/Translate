# functions/process_audio/main.py

import os
import json
import base64
import time
from google.cloud import pubsub_v1
import logging

def process_audio(request):
    """Process audio file and publish to Pub/Sub for streaming recognition."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        if request.method != 'POST':
            return json.dumps({'error': 'Method not allowed'}), 405

        # Parse request
        try:
            request_json = request.get_json()
        except Exception as e:
            logger.error(f"Failed to parse request JSON: {str(e)}")
            return json.dumps({'error': 'Invalid JSON'}), 400

        # Validate parameters
        meeting_code = request_json.get('meetingCode')
        source_language = request_json.get('sourceLanguage')
        audio_data = request_json.get('audioData')
        client_id = request_json.get('clientId')  # Speaker's client ID

        if not all([meeting_code, source_language, audio_data, client_id]):
            missing = [k for k in ['meetingCode', 'sourceLanguage', 'audioData', 'clientId'] 
                      if not request_json.get(k)]
            logger.error(f"Missing required parameters: {missing}")
            return json.dumps({'error': f'Missing parameters: {missing}'}), 400

        logger.info(f"Processing audio for meeting {meeting_code} from client {client_id}")

        try:
            # Validate base64 data
            decoded_audio = base64.b64decode(audio_data)
            logger.info(f"Successfully decoded audio data: {len(decoded_audio)} bytes")
        except Exception as e:
            logger.error(f"Failed to decode base64 audio data: {str(e)}")
            return json.dumps({'error': 'Invalid audio data encoding'}), 400










        # Initialize Pub/Sub client
        try:
            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(os.getenv('PROJECT_ID'), 'audio-fragments')
            logger.info(f"Publishing to topic: {topic_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Pub/Sub client: {str(e)}")
            return json.dumps({'error': 'Failed to initialize Pub/Sub'}), 500

        # Publish to Pub/Sub


        # Right before publishing
        logger.info(f"Publishing message to {topic_path}")
        logger.info("Message attributes:")
        logger.info(f"- Meeting Code: {meeting_code}")
        logger.info(f"- Source Language: {source_language}")
        logger.info(f"- Client ID: {client_id}")
        logger.info(f"- Timestamp: {time.time()}")
        logger.info(f"Audio data size: {len(decoded_audio)} bytes")

        # Publish to Pub/Sub
        try:
            future = publisher.publish(
                topic_path,
                data=decoded_audio,
                meetingCode=meeting_code,
                sourceLanguage=source_language,
                clientId=client_id,
                timestamp=str(time.time())
            )

            message_id = future.result()
            logger.info(f"Successfully published message {message_id}")
            
            return json.dumps({
                'success': True,
                'messageId': message_id,
                'audioSize': len(decoded_audio),
                'timestamp': time.time()
            }), 200

        except Exception as e:
            logger.error(f"Failed to publish message to Pub/Sub: {str(e)}")
            return json.dumps({'error': f'Failed to publish message: {str(e)}'}), 500

    except Exception as e:
        logger.error(f"Error in process_audio: {str(e)}")
        return json.dumps({'error': str(e)}), 500