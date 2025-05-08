import plivo
from quart import Quart, websocket, Response, request
import asyncio
import websockets
import json
import base64
import os
import logging
import google.generativeai as genai
from pinecone import Pinecone
from dotenv import load_dotenv
import time
from realtime_tools import search_product_database
from number import extract_mobile_numbers
from tools import send_simple_whatsapp, generate_inquiry_invoice
# Load environment variables
load_dotenv(dotenv_path='.env', override=True)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment variables and constants
PORT = 5000
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GENAI_API_KEY = os.getenv("GOOGLE_API_KEY")
DEFAULT_NAMESPACE = "Tec Nviirons Sample data testing.xlsx 2025-05-02 09:05:24"

# Configure APIs
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please add it to your .env file")

genai.configure(api_key=GENAI_API_KEY)

# System prompt for the assistant
SYSTEM_MESSAGE = (
    "You are a helpful assistant who can answer product-related questions using a product database. "
    "If the user asks about a product, you'll search the database to provide accurate information. "
    "For other topics, you'll be friendly and conversational."
)

app = Quart(__name__)

# Store call data separately for each call UUID
call_data = {}

@app.route("/webhook", methods=["GET", "POST"])
async def home():
    # Extract caller information
    values = await request.values
    caller_number = values.get('From', 'unknown')
    called_number = values.get('To', 'unknown')
    call_uuid = values.get('CallUUID', 'unknown')
    
    # Log the incoming call
    print(f"Incoming call from {caller_number} to {called_number} (UUID: {call_uuid})")
    
    # Initialize data structures for this call
    call_data[call_uuid] = {
        'caller_number': caller_number,
        'called_number': called_number,
        'timestamp': time.time(),
        'transcriptions': {},
        'function_calls': []
    }
    
    xml_data = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Stream streamTimeout="86400" keepCallAlive="true" bidirectional="true" contentType="audio/x-mulaw;rate=8000" audioTrack="inbound" >
            ws://{request.host}/media-stream/{call_uuid}
        </Stream>
    </Response>
    '''
    return Response(xml_data, mimetype='application/xml')


@app.websocket('/media-stream/<call_uuid>')
async def handle_message(call_uuid):
    print(f'Client connected for call UUID: {call_uuid}')
    plivo_ws = websocket 
    
    # Ensure we have data for this call
    if call_uuid not in call_data:
        print(f"Warning: No call data found for UUID {call_uuid}, creating empty data")
        call_data[call_uuid] = {
            'caller_number': 'unknown',
            'called_number': 'unknown',
            'timestamp': time.time(),
            'transcriptions': {},
            'function_calls': []
        }
    
    caller_number = call_data[call_uuid]['caller_number']
    print(f"Processing call from: {caller_number} with UUID: {call_uuid}")
    
    # Pass call info to the WebSocket session
    plivo_ws.caller_number = caller_number
    plivo_ws.call_uuid = call_uuid

    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    try: 
        async with websockets.connect(url, extra_headers=headers) as openai_ws:
            print(f'Connected to the OpenAI Realtime API for call {call_uuid}')

            await send_session_update(openai_ws)
            
            receive_task = asyncio.create_task(receive_from_plivo(plivo_ws, openai_ws, call_uuid))
            
            async for message in openai_ws:
                await receive_from_openai(message, plivo_ws, openai_ws, call_uuid)
            
            await receive_task
    
    except asyncio.CancelledError:
        print(f'Client disconnected for call {call_uuid}')
        await after_call_hangup(call_uuid)
    except websockets.ConnectionClosed:
        print(f"Connection closed by OpenAI server for call {call_uuid}")
        await after_call_hangup(call_uuid)
    except Exception as e:
        print(f"Error during OpenAI's websocket communication for call {call_uuid}: {e}")
        await after_call_hangup(call_uuid)
        
async def receive_from_plivo(plivo_ws, openai_ws, call_uuid):
    try:
        while True:
            message = await plivo_ws.receive()
            data = json.loads(message)
            if data['event'] == 'media' and openai_ws.open:
                audio_append = {
                    "type": "input_audio_buffer.append",
                    "audio": data['media']['payload']
                }
                await openai_ws.send(json.dumps(audio_append))
            elif data['event'] == "start":
                print(f'Plivo Audio stream has started for call {call_uuid}')
                plivo_ws.stream_id = data['start']['streamId']
            elif data['event'] == "hangup":
                print(f'Call has ended for call {call_uuid}')
                await after_call_hangup(call_uuid)
                if openai_ws.open:
                    await openai_ws.close()

    except websockets.ConnectionClosed:
        print(f'Connection closed for the plivo audio streaming servers for call {call_uuid}')
        await after_call_hangup(call_uuid)
        if openai_ws.open:
            await openai_ws.close()
    except Exception as e:
        print(f"Error during Plivo's websocket communication for call {call_uuid}: {e}")
        await after_call_hangup(call_uuid)

async def receive_from_openai(message, plivo_ws, openai_ws, call_uuid):
    try:
        response = json.loads(message)
        print(f'Response received from OpenAI Realtime API for call {call_uuid}: {response["type"]}')
        
        if response['type'] == 'session.updated':
           print(f'Session updated successfully for call {call_uuid}')
        elif response['type'] == 'error':
            print(f'Error received from realtime api for call {call_uuid}: {response}')
        elif response['type'] == 'response.audio.delta':
            audio_delta = {
               "event": "playAudio",
                "media": {
                    "contentType": 'audio/x-mulaw',
                    "sampleRate": 8000,
                    "payload": base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                }
            }
            await plivo_ws.send(json.dumps(audio_delta))
        elif response['type'] == 'response.function_call_arguments.done':
            print(f'Received function call response for call {call_uuid}: {response}')
            if response['name'] == 'search_product_database':
                # Call the RAG function with the query
                args = json.loads(response['arguments'])
                query = args['query']
                result = await search_product_database(args['query'])
                
                # Record the function call and its result
                if call_uuid in call_data:
                    call_data[call_uuid]['function_calls'].append({
                        'timestamp': time.time(),
                        'query': query,
                        'result': result,
                        'item_id': response['item_id']
                    })
                
                # Send the RAG function output back to OpenAI
                output = function_call_output(result, response['item_id'], response['call_id'])
                await openai_ws.send(json.dumps(output))
                
                # Generate a response using the RAG result
                generate_response = {
                    "type": "response.create",
                    "response": {
                        "modalities": ["text", "audio"],
                        "temperature": 0.8,
                        "instructions": 'Share the product information from the database search with the user in a helpful way.'
                    }
                }
                print(f"Sending RAG search result response for call {call_uuid}")
                await openai_ws.send(json.dumps(generate_response))
        # Handle transcription delta events
        elif response['type'] == 'conversation.item.input_audio_transcription.delta':
            item_id = response.get('item_id')
            delta = response.get('delta', '')
            
            if call_uuid in call_data:
                if item_id not in call_data[call_uuid]['transcriptions']:
                    call_data[call_uuid]['transcriptions'][item_id] = {'text': delta, 'complete': False}
                else:
                    call_data[call_uuid]['transcriptions'][item_id]['text'] += delta
            
            print(f"Transcription delta for call {call_uuid}, item {item_id}: {delta}")
            
        # Handle transcription completed events
        elif response['type'] == 'conversation.item.input_audio_transcription.completed':
            item_id = response.get('item_id')
            full_transcript = response.get('transcript', '')
            
            if call_uuid in call_data:
                call_data[call_uuid]['transcriptions'][item_id] = {'text': full_transcript, 'complete': True}
            print(f"Transcription completed for call {call_uuid}, item {item_id}: {full_transcript}")
                
        elif response['type'] == 'input_audio_buffer.speech_started':
            print(f'Speech started for call {call_uuid}')
            clear_audio_data = {
                "event": "clearAudio",
                "stream_id": plivo_ws.stream_id
            }
            await plivo_ws.send(json.dumps(clear_audio_data))
            cancel_response = {
                "type": "response.cancel"
            }
            await openai_ws.send(json.dumps(cancel_response))
    except Exception as e:
        print(f"Error during OpenAI's websocket communication for call {call_uuid}: {e}")
    
async def send_session_update(openai_ws):
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "tools": [
                {
                    "type": "function",
                    "name": "search_product_database",
                    "description": "Search for product information in the database",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": { 
                                "type": "string", 
                                "description": "The search query about a product or part"
                            }
                        },
                        "required": ["query"]
                    }
                }
            ],
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": "alloy",
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            "input_audio_transcription": {
                "model": "gpt-4o-transcribe",
                "language": "en"
            },
            "include": ["item.input_audio_transcription.logprobs"]
        }
    }
    await openai_ws.send(json.dumps(session_update))

def function_call_output(result, item_id, call_id):
    conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "id": item_id,
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps({"result": result})
        }
    }
    return conversation_item

async def after_call_hangup(call_uuid):
    """Process transcriptions, generate invoice, and send via WhatsApp for a specific call"""
    # Check if we have data for this call
    if call_uuid not in call_data:
        print(f"No call data found for UUID {call_uuid}")
        return
        
    call_info = call_data[call_uuid]
    transcriptions = call_info['transcriptions']
    function_calls = call_info['function_calls']
    
    if not transcriptions and not function_calls:
        print(f"No transcriptions or function calls recorded for call {call_uuid}")
        # Clean up call data
        if call_uuid in call_data:
            del call_data[call_uuid]
        return
        
    print(f"\n====== CALL {call_uuid} TRANSCRIPT & FUNCTION CALLS ======")
    
    # Prepare both transcriptions and function calls with timestamps
    conversation_events = []
    
    # Add user transcriptions
    sorted_items = sorted(transcriptions.items(), key=lambda x: x[0])
    for i, (item_id, data) in enumerate(sorted_items):
        conversation_events.append({
            'type': 'transcript',
            'order': i,
            'item_id': item_id,
            'text': data['text']
        })
    
    # Add function calls with their actual timestamps
    for i, call in enumerate(function_calls):
        conversation_events.append({
            'type': 'function_call',
            'order': len(sorted_items) + i,
            'item_id': call['item_id'],
            'query': call['query'],
            'result': call['result']
        })
    
    # Sort all events by our order field
    conversation_events.sort(key=lambda x: x['order'])
    
    # Print all events in order
    for event in conversation_events:
        if event['type'] == 'transcript':
            print(f"User: {event['text']}")
        else:
            print(f"Function Call Query: {event['query']}")
            print(f"Function Call Result: {event['result']}\n")
    
    print("============================================\n")
    
    # Format transcript data as string
    transcript_text = "CALL TRANSCRIPT & DATABASE QUERIES\n"
    transcript_text += "=================================\n\n"
    
    for event in conversation_events:
        if event['type'] == 'transcript':
            transcript_text += f"User: {event['text']}\n"
        else:
            transcript_text += f"\nDATABASE QUERY: {event['query']}\n"
            transcript_text += f"RESULT: {event['result']}\n\n"
    
    # Get the caller number from call data
    caller_number_raw = call_info.get('caller_number', 'unknown')
    
    # Extract valid mobile number using extract_mobile_numbers function
    valid_numbers = extract_mobile_numbers(caller_number_raw, country="NP")
    recipient_number = valid_numbers[0] if valid_numbers else caller_number_raw
    print(f"Extracted recipient number for call {call_uuid}: {recipient_number}")
    
    # Generate invoice from transcript data
    invoice = generate_inquiry_invoice(transcript_text)
    print(f"Generated invoice summary for call {call_uuid}:")
    print(invoice)
    
    # Send WhatsApp message with the invoice
    try:
        send_simple_whatsapp(recipient_number, invoice)
        print(f"WhatsApp invoice sent successfully to {recipient_number} for call {call_uuid}")
    except Exception as e:
        print(f"Failed to send WhatsApp message for call {call_uuid}: {e}")
    
    # Clean up call data
    if call_uuid in call_data:
        print(f"Cleaning up data for call {call_uuid}")
        del call_data[call_uuid]


if __name__ == "__main__":
    print('running the server')
    app.run(port=PORT)
