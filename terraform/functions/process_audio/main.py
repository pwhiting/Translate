import os
import json
import base64
import wave
import io
from google.cloud import speech_v1
from google.cloud import translate_v2
from google.cloud import firestore
import logging

def get_next_sequence(transaction, meeting_ref):
    """Get and increment the sequence number atomically."""
    sequence_doc = meeting_ref.collection('metadata').document('sequence')
    sequence = sequence_doc.get(transaction=transaction)
    
    if not sequence.exists:
        current_value = 0
    else:
        sequence_data = sequence.to_dict()
        current_value = sequence_data.get('value', 0)
    
    next_value = current_value + 1
    transaction.set(sequence_doc, {'value': next_value})
    return next_value

def process_audio(request):
    """Process audio file for speech recognition and translation."""
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

        if not all([meeting_code, source_language, audio_data]):
            missing = [k for k in ['meetingCode', 'sourceLanguage', 'audioData'] 
                      if not request_json.get(k)]
            return json.dumps({'error': f'Missing parameters: {missing}'}), 400

        # Process audio
        try:
            decoded_audio = base64.b64decode(audio_data)
            
            with io.BytesIO(decoded_audio) as wav_io:
                with wave.open(wav_io, 'rb') as wav_file:
                    pcm_data = wav_file.readframes(wav_file.getnframes())
                    
        except Exception as e:
            logger.error(f"Audio processing error: {str(e)}")
            return json.dumps({'error': f'Audio processing error: {str(e)}'}), 400

        # Initialize clients
        speech_client = speech_v1.SpeechClient()
        translate_client = translate_v2.Client()
        db = firestore.Client()

        # Perform speech recognition
        audio = speech_v1.RecognitionAudio(content=pcm_data)
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=source_language,
            enable_automatic_punctuation=True
        )
        
        response = speech_client.recognize(config=config, audio=audio)
        
        if not response.results:
            return json.dumps({
                'success': True,
                'transcription': '',
                'translations': []
            }), 200

        transcription = response.results[0].alternatives[0].transcript
        confidence = response.results[0].alternatives[0].confidence

        # Get meeting info and perform translations
        meeting_ref = db.collection('meetings').document(meeting_code)
        meeting = meeting_ref.get()
        
        if not meeting.exists:
            return json.dumps({'error': 'Meeting not found'}), 404

        target_languages = meeting.to_dict().get('targetLanguages', [])
        translations = []
        
        # Use a transaction to get sequence numbers and store translations
        transaction = db.transaction()
        translations_generated = 0

        @firestore.transactional
        def update_in_transaction(transaction, meeting_ref):
            nonlocal translations_generated
            
            sequence = get_next_sequence(transaction, meeting_ref)
            batch = db.batch()

            for target_lang in target_languages:
                if target_lang != source_language:
                    try:
                        logger.info(f"Translating to {target_lang}")
                        translation = translate_client.translate(
                            transcription,
                            target_language=target_lang,
                            source_language=source_language.split('-')[0]
                        )
                        
                        translation_data = {
                            'sourceText': transcription,
                            'sourceLanguage': source_language,
                            'targetLanguage': target_lang,
                            'translatedText': translation['translatedText'],
                            'sequence': sequence,
                            'confidence': confidence,
                            'isComplete': True
                        }
                        
                        # Store in Firestore
                        translation_ref = meeting_ref.collection('translations').document()
                        transaction.set(translation_ref, translation_data)
                        
                        # Add to response
                        translations.append({
                            'targetLanguage': target_lang,
                            'translatedText': translation['translatedText']
                        })
                        
                        translations_generated += 1
                        
                    except Exception as e:
                        logger.error(f"Translation error for {target_lang}: {str(e)}")
                        continue
            
            return translations

        # Execute the transaction
        update_in_transaction(transaction, meeting_ref)
        
        return json.dumps({
            'success': True,
            'transcription': transcription,
            'confidence': confidence,
            'translations': translations,
            'translations_generated': translations_generated
        }), 200

    except Exception as e:
        logger.error(f"Error in process_audio: {str(e)}")
        return json.dumps({'error': str(e)}), 500