import os
import json
import random
import string
from google.cloud import firestore
import logging



def generate_meeting_code():
    """Generate a random 6-character uppercase meeting code."""
    return ''.join(random.choices(string.ascii_uppercase, k=6))

def generate_participant_id():
    """Generate a unique participant ID."""
    return f"p{''.join(random.choices(string.digits, k=10))}"

def join_meeting(request):
    """Handle meeting join requests."""
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    if request.method != 'POST':
        return json.dumps({'error': 'Method not allowed'}), 405, {'Content-Type': 'application/json'}
    
    try:
        request_data = request.get_json()
        meeting_code = request_data.get('meetingCode')
        target_language = request_data.get('targetLanguage')
        
        logger.debug(f"Join request for meeting {meeting_code} with language {target_language}")
        
        if not meeting_code or not target_language:
            return json.dumps({'error': 'Missing required parameters'}), 400, {'Content-Type': 'application/json'}
        
        db = firestore.Client()
        meeting_ref = db.collection('meetings').document(meeting_code)
        meeting = meeting_ref.get()
        
        participant_id = generate_participant_id()
        
        if not meeting.exists:
            # Create new meeting if it doesn't exist
            logger.info(f"Creating new meeting {meeting_code}")
            
            # Create in transaction to ensure sequence number is initialized
            transaction = db.transaction()

            @firestore.transactional
            def create_meeting(transaction, meeting_ref):
                meeting_ref.set({
                    'code': meeting_code,
                    'status': 'active',
                    'targetLanguages': [target_language],
                    'participants': {
                        participant_id: target_language
                    }
                })
                
                # Initialize sequence counter
                sequence_ref = meeting_ref.collection('metadata').document('sequence')
                transaction.set(sequence_ref, {'value': 0})
            
            create_meeting(transaction, meeting_ref)
        else:
            # Update existing meeting
            logger.info(f"Updating existing meeting {meeting_code}")
            meeting_data = meeting.to_dict()
            if target_language not in meeting_data.get('targetLanguages', []):
                meeting_ref.update({
                    'targetLanguages': firestore.ArrayUnion([target_language]),
                    f'participants.{participant_id}': target_language
                })
            else:
                meeting_ref.update({
                    f'participants.{participant_id}': target_language
                })
        
        return json.dumps({
            'success': True,
            'participantId': participant_id
        }), 200, {'Content-Type': 'application/json'}
        
    except Exception as e:
        logger.error(f"Error in join_meeting: {str(e)}")
        return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
    

