import json
import time
from google.cloud import firestore
import logging

def get_translations(request):
    """Retrieve translations for a meeting participant."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        meeting_code = request.args.get('meetingCode')
        target_language = request.args.get('targetLanguage')
        last_sequence = request.args.get('sequence')

        logger.info(f"Getting translations for meeting {meeting_code}, language {target_language}, after sequence {last_sequence}")

        if not meeting_code or not target_language:
            return json.dumps({'error': 'Missing required parameters'}), 400

        # Handle initial registration request

        if last_sequence is None:
            logger.info("Processing initial registration request")
                # Initialize Firestore client
            db = firestore.Client()
            # Get the latest sequence number
            metadata_ref = db.collection('meetings').document(meeting_code).collection('metadata').document('sequence')
            sequence_doc = metadata_ref.get()
            current_sequence = 0 if not sequence_doc.exists else sequence_doc.to_dict().get('value', 0)
            
            logger.info(f"Starting from sequence number: {current_sequence}")
            
            return json.dumps({
                'success': True,
                'translations': [{
                    'id': 'registration',
                    'messageId': 'registration',
                    'translatedText': '',
                    'sourceLanguage': '',
                    'targetLanguage': target_language,
                    'sequence': current_sequence,  # Use the current sequence instead of 0
                    'isComplete': True,
                    'empty': True
                }]
            }), 200

        # Initialize Firestore
        db = firestore.Client()
        translations_ref = db.collection('meetings').document(meeting_code).collection('translations')
        
        # Wait up to 15 seconds for new content
        start_time = time.time()
        results = []
        last_sequence = int(last_sequence)
        
        while time.time() - start_time < 15:
            # Create fresh query each time
            query = translations_ref
            query = query.where('targetLanguage', '==', target_language)
            query = query.where('isComplete', '==', True)
            query = query.where('sequence', '>', last_sequence)
            query = query.order_by('sequence')

            logger.info(f"Executing query for translations after sequence {last_sequence}")
            translations = query.stream()
            
            for doc in translations:
                data = doc.to_dict()
                sequence = data.get('sequence')
                
                if sequence is not None:
                    logger.info(f"Found translation with sequence {sequence}")
                    results.append({
                        'translatedText': data.get('translatedText', ''),
                        'sourceLanguage': data.get('sourceLanguage', ''),
                        'sequence': sequence
                    })
            
            if results:
                logger.info(f"Found {len(results)} translations")
                break
                
            logger.info("No results yet, waiting...")
            time.sleep(1)  # Poll every second

        # If no results after waiting, return empty response
        if not results:
            logger.info("No translations found after waiting, returning empty response")
            return json.dumps({
                'success': True,
                'translations': [{
                    'id': f'empty_{last_sequence}',
                    'messageId': f'empty_{last_sequence}',
                    'translatedText': '',
                    'sourceLanguage': '',
                    'targetLanguage': target_language,
                    'sequence': last_sequence,
                    'isComplete': True,
                    'empty': True
                }]
            }), 200

        # Sort by sequence and concatenate texts
        results.sort(key=lambda x: x['sequence'])
        concatenated_text = ' '.join(r['translatedText'].strip() for r in results)
        highest_sequence = results[-1]['sequence']

        logger.info(f"Returning concatenated text with highest sequence {highest_sequence}")
        
        return json.dumps({
            'success': True,
            'translations': [{
                'id': f'concat_{highest_sequence}',
                'messageId': f'concat_{highest_sequence}',
                'translatedText': concatenated_text,
                'sourceLanguage': results[0]['sourceLanguage'],
                'targetLanguage': target_language,
                'sequence': highest_sequence,
                'isComplete': True,
                'empty': False
            }]
        }), 200

    except Exception as e:
        logger.error(f"Error in get_translations: {str(e)}")
        return json.dumps({'error': str(e)}), 500