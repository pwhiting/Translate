import os
import json
import logging
from google.cloud import pubsub_v1
from google.api_core.exceptions import DeadlineExceeded
def get_translations(request):
    """Retrieve translations using Pub/Sub subscription."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    try:
        meeting_code = request.args.get('meetingCode')
        target_language = request.args.get('targetLanguage')
        client_id = request.args.get('clientId')
        
        logger.info(f"Translation request: meeting={meeting_code}, language={target_language}, client={client_id}")
        
        if not all([meeting_code, target_language, client_id]):
            return json.dumps({
                'success': False,
                'error': 'Missing required parameters'
            }), 400
        # Initialize Pub/Sub subscriber
        subscriber = pubsub_v1.SubscriberClient()
        subscription_path = subscriber.subscription_path(
            os.getenv('PROJECT_ID'),
            f"meeting-{meeting_code}-{target_language}-client-{client_id}"
        )
        try:
            # Pull messages - note removal of timeout parameter
            pull_response = subscriber.pull(
                request={
                    "subscription": subscription_path,
                    "max_messages": 10
                }
            )
            
            messages = []
            ack_ids = []
            
            for msg in pull_response.received_messages:
                messages.append({
                    'messageId': msg.message.message_id,
                    'translatedText': msg.message.data.decode('utf-8'),
                    'timestamp': msg.message.publish_time.timestamp(),
                    'attributes': dict(msg.message.attributes)
                })
                ack_ids.append(msg.ack_id)
            
            # Acknowledge received messages
            if ack_ids:
                logger.info(f"Acknowledging {len(ack_ids)} messages")
                subscriber.acknowledge(
                    request={
                        "subscription": subscription_path,
                        "ack_ids": ack_ids
                    }
                )
            
            return json.dumps({
                'success': True,
                'translations': messages
            }), 200
            
        except Exception as e:
            logger.error(f"Error pulling messages: {str(e)}")
            return json.dumps({
                'success': True,
                'translations': [],
                'error': str(e)
            }), 200
    except Exception as e:
        logger.error(f"Error in get_translations: {str(e)}")
        return json.dumps({
            'success': False,
            'error': str(e)
        }), 500
