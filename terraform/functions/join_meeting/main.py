# functions/join_meeting/main.py

import os
import json
import logging
import uuid
from google.cloud import pubsub_v1
from google.cloud import firestore
from google.api_core.exceptions import NotFound

def generate_client_id():
    """Generate a unique client ID."""
    return str(uuid.uuid4())

def join_meeting(request):
    """Handle meeting join requests."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    try:
        request_data = request.get_json()
        meeting_code = request_data.get('meetingCode')
        target_language = request_data.get('targetLanguage')
        client_id = request_data.get('clientId', generate_client_id())  # Using the helper function
        
        logger.info(f"Join request: meeting={meeting_code}, language={target_language}")
        
        if not meeting_code or not target_language:
            return json.dumps({'error': 'Missing required parameters'}), 400

        # Initialize clients
        publisher = pubsub_v1.PublisherClient()
        subscriber = pubsub_v1.SubscriberClient()
        db = firestore.Client()
        
        # Format topic and subscription IDs
        topic_id = f"meeting-{meeting_code}-{target_language}"
        subscription_id = f"{topic_id}-client-{client_id}"
        
        # Get or create topic
        topic_path = publisher.topic_path(os.getenv('PROJECT_ID'), topic_id)
        try:
            topic = publisher.get_topic(request={'topic': topic_path})
            logger.info(f"Found existing topic: {topic_id}")
        except NotFound:
            logger.info(f"Creating new topic: {topic_id}")
            topic = publisher.create_topic(request={'name': topic_path})
        
        # Create subscription
        subscription_path = subscriber.subscription_path(os.getenv('PROJECT_ID'), subscription_id)
        try:
            subscription = subscriber.get_subscription(request={'subscription': subscription_path})
            logger.info(f"Found existing subscription: {subscription_id}")
        except NotFound:
            logger.info(f"Creating new subscription: {subscription_id}")
            subscription = subscriber.create_subscription(
                request={
                    'name': subscription_path,
                    'topic': topic_path
                }
            )
        
        # Store/update meeting metadata
        meeting_ref = db.collection('meetings').document(meeting_code)
        if not meeting_ref.get().exists:
            meeting_ref.set({
                'code': meeting_code,
                'status': 'active',
                'created': firestore.SERVER_TIMESTAMP,
                'targetLanguages': [target_language]
            })
        else:
            meeting_ref.update({
                'targetLanguages': firestore.ArrayUnion([target_language]),
                'lastActivity': firestore.SERVER_TIMESTAMP
            })
        
        return json.dumps({
            'success': True,
            'clientId': client_id,
            'subscriptionPath': subscription_path
        }), 200
        
    except Exception as e:
        logger.error(f"Error in join_meeting: {str(e)}")
        return json.dumps({'error': str(e)}), 500