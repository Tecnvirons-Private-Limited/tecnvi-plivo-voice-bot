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
INDEX_NAME = "voice-bot-gemini-embedding-004-index"

# Configure APIs
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is not set. Please add it to your .env file")

genai.configure(api_key=GENAI_API_KEY)

# Set up Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)
try:
    index = pc.Index(INDEX_NAME)
    logger.info(f"Connected to Pinecone index: {INDEX_NAME}")
except Exception as e:
    logger.error(f"Pinecone setup error: {e}")
    raise

# System prompt for the assistant
SYSTEM_MESSAGE = (
    "You are a helpful assistant who can answer product-related questions using a product database. "
    "If the user asks about a product, you'll search the database to provide accurate information. "
    "For other topics, you'll be friendly and conversational."
)

app = Quart(__name__)

@app.route("/webhook", methods=["GET", "POST"])
def home():
    xml_data = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Stream streamTimeout="86400" keepCallAlive="true" bidirectional="true" contentType="audio/x-mulaw;rate=8000" audioTrack="inbound" >
            ws://{request.host}/media-stream
        </Stream>
    </Response>
    '''
    return Response(xml_data, mimetype='application/xml')


@app.websocket('/media-stream')
async def handle_message():
    print('client connected')
    plivo_ws = websocket 
    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    try: 
        async with websockets.connect(url, extra_headers=headers) as openai_ws:
            print('connected to the OpenAI Realtime API')

            await send_session_update(openai_ws)
            
            receive_task = asyncio.create_task(receive_from_plivo(plivo_ws, openai_ws))
            
            async for message in openai_ws:
                await receive_from_openai(message, plivo_ws, openai_ws)
            
            await receive_task
    
    except asyncio.CancelledError:
        print('client disconnected')
    except websockets.ConnectionClosed:
        print("Connection closed by OpenAI server")
    except Exception as e:
        print(f"Error during OpenAI's websocket communication: {e}")
        
async def receive_from_plivo(plivo_ws, openai_ws):
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
                print('Plivo Audio stream has started')
                plivo_ws.stream_id = data['start']['streamId']

    except websockets.ConnectionClosed:
        print('Connection closed for the plivo audio streaming servers')
        if openai_ws.open:
            await openai_ws.close()
    except Exception as e:
        print(f"Error during Plivo's websocket communication: {e}")

async def receive_from_openai(message, plivo_ws, openai_ws):
    try:
        response = json.loads(message)
        print('response received from OpenAI Realtime API: ', response['type'])
        
        if response['type'] == 'session.updated':
           print('session updated successfully')
        elif response['type'] == 'error':
            print('error received from realtime api: ', response)
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
            print('received function call response ', response)
            if response['name'] == 'search_product_database':
                # Call the RAG function with the query
                args = json.loads(response['arguments'])
                result = await search_product_database(args['query'])
                
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
                print("sending RAG search result response")
                await openai_ws.send(json.dumps(generate_response))
                
        elif response['type'] == 'input_audio_buffer.speech_started':
            print('speech is started')
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
        print(f"Error during OpenAI's websocket communication: {e}")
    
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
            "temperature": 0.8
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

# RAG search function from example.py
async def search_product_database(query, namespace=DEFAULT_NAMESPACE):
    """Search product information in vector database"""
    try:
        # Logs the query and namespace so developers can see what's being searched.
        logger.info(f"Searching for: '{query}' in namespace '{namespace}'")
        embed_response = genai.embed_content(
            model="models/text-embedding-004", 
            content=query
        )
        embedding = embed_response["embedding"]
        results = index.query(
            vector=embedding,
            namespace=namespace,
            top_k=2,
            include_metadata=True
        )
        print(f"Search results: {results}")        
        if not results["matches"]:
            return "I couldn't find information about that product in our database."
        
        contexts = []
        for match in results["matches"]:
            if "text" in match.get("metadata", {}):
                contexts.append(match["metadata"]["text"])
                
        if not contexts:
            return "I found some matches but they don't contain usable information."
        
        context_text = "\n---\n".join(contexts)
        summary_prompt = f"""
        Based on these product details:
        {context_text}
        
        For any product information with "Unnamed" labels, extract and present it in this format:
        - Product Name: [The product name from the first "Unnamed" field]
        - Quantity: [The quantity number, usually after a date range]
        - Unit Price: [The price value]
        - Total Cost: [The total cost value]
        
        For example, if you see:
        "Unnamed: 0: BOLT ALLEN M6X10LX1P RH SS 202
        1-Apr-24 to 1-Mar-25: 100
        Unnamed: 2: 9.86
        Unnamed: 3: 985.64"
        
        Present it as:
        - Product Name: BOLT ALLEN M6X10LX1P RH SS
        - Quantity: 100
        - Unit Price: $9.86
        - Total Cost: $985.64
        
        Answer this question concisely: {query}
        """

        summary = genai.GenerativeModel("gemini-1.5-flash").generate_content(summary_prompt)
        return summary.text

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        return f"Sorry, I encountered an error searching our product database."

if __name__ == "__main__":
    print('running the server')
    # client = plivo.RestClient(auth_id=os.getenv('PLIVO_AUTH_ID'), auth_token=os.getenv('PLIVO_AUTH_TOKEN'))

    # # Make an outbound call
    # call_made = client.calls.create(
    #     from_=os.getenv('PLIVO_FROM_NUMBER'),
    #     to_=os.getenv('PLIVO_TO_NUMBER'),
    #     answer_url=os.getenv('PLIVO_ANSWER_XML'),
    #     answer_method='GET',)
    
    app.run(port=PORT)
