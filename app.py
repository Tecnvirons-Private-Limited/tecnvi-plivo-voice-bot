import os
import asyncio
import json
import base64
import logging
import time
from queue import Queue
import websockets
from dotenv import load_dotenv
from quart import Quart, Response, request, websocket
import google.generativeai as genai
from pinecone import Pinecone

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger('websockets.client').setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PLIVO_AUTH_ID = os.getenv('PLIVO_AUTH_ID')
PLIVO_AUTH_TOKEN = os.getenv('PLIVO_AUTH_TOKEN')
PLIVO_FROM_NUMBER = os.getenv('PLIVO_FROM_NUMBER')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')

# Validate required environment variables
required_vars = [
    "OPENAI_API_KEY", "PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN",
    "GOOGLE_API_KEY", "PINECONE_API_KEY"
]
for var in required_vars:
    if not os.getenv(var):
        raise ValueError(f"❌ {var} is missing in .env")

# Application settings
PORT = 5000
SYSTEM_MESSAGE = (
    "You are a helpful product assistant. When users ask about products, "
    "you will receive specific information to include in your response. "
    "Provide clear and friendly answers based on this information, "
    "and maintain a natural conversation."
)

# Create Quart app
app = Quart(__name__)

# Initialize global variables
pinecone_index = None
pinecone_ready = False
gemini_ready = False

# Shared states
current_transcript = ""
speech_in_progress = False
openai_responding = False
pending_pinecone_query = False

# NEW: Add locks to control event flow
class ResponseControl:
    def __init__(self):
        self.response_lock = asyncio.Lock()
        self.can_respond = False
        self.processing_complete = asyncio.Event()
        self.context_updated = False

response_control = ResponseControl()

def initialize_services():
    """Initialize Gemini and Pinecone services"""
    global pinecone_index, pinecone_ready, gemini_ready
    
    try:
        # Initialize Gemini
        logger.info("Configuring Gemini API...")
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        
        # Test Gemini with a simple query
        test_model = genai.GenerativeModel("gemini-1.5-flash")
        test_response = test_model.generate_content("Hello, are you working?")
        logger.info(f"Gemini test response: {test_response.text[:50]}...")
        logger.info("✅ Gemini API confirmed working")
        gemini_ready = True

        # Initialize Pinecone
        logger.info("Initializing Pinecone client...")
        pinecone_client = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        
        # List available indexes to verify connection
        available_indexes = pinecone_client.list_indexes().names()
        logger.info(f"Available Pinecone indexes: {available_indexes}")
        
        # Setup Pinecone index
        index_name = "voice-bot-gemini-embedding-004-index"
        
        if index_name not in available_indexes:
            logger.info(f"Creating new Pinecone index: {index_name}...")
            pinecone_client.create_index(
                name=index_name,
                dimension=768,
                metric="cosine"
            )
            logger.info("✅ New Pinecone index created")
        else:
            logger.info(f"✅ Using existing Pinecone index: {index_name}")

        pinecone_index = pinecone_client.Index(index_name)
        
        # Verify the index is accessible
        index_stats = pinecone_index.describe_index_stats()
        logger.info(f"Pinecone index stats: {index_stats}")
        logger.info("✅ Pinecone index connection confirmed")
        pinecone_ready = True

        # Successfully initialized services
        return True

    except Exception as e:
        logger.error(f"❌ Error during service initialization: {str(e)}", exc_info=True)
        return False

# Initialize services on startup
if not initialize_services():
    logger.error("❌ Failed to initialize services, application may not function correctly")

async def generate_embedding(text):
    """Generate embedding for text using Gemini"""
    try:
        query_response = genai.embed_content(
            model="models/text-embedding-004",
            content=text
        )
        return query_response["embedding"]
    except Exception as e:
        logger.error(f"❌ Error generating embedding: {str(e)}", exc_info=True)
        return None

async def search_pinecone(embedding):
    """Search Pinecone index with embedding"""
    try:
        search_results = pinecone_index.query(
            vector=embedding,
            top_k=3,
            include_metadata=True
        )
        return search_results
    except Exception as e:
        logger.error(f"❌ Error searching Pinecone: {str(e)}", exc_info=True)
        return None

async def generate_answer_with_gemini(query, context):
    """Generate answer using Gemini with context"""
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
You are a helpful assistant that answers questions about products based on the provided information.

Question: {query}

Context: {context}

Please provide a clear and concise answer based on the context. Only include factual information from the context.
If you don't have enough information to answer the question, say so.
"""
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"❌ Error generating answer with Gemini: {str(e)}", exc_info=True)
        return None

async def process_user_query(query):
    """Full pipeline to process user query with Pinecone and Gemini"""
    if not query or query.strip() == "":
        return None
    
    logger.info(f"🔍 Processing query: '{query}'")
    
    # 1. Generate embedding
    logger.info("1️⃣ Generating embedding...")
    embedding = await generate_embedding(query)
    if not embedding:
        return "I'm having trouble understanding your request."
    
    # 2. Search Pinecone
    logger.info(f"2️⃣ Searching Pinecone with embedding (dim: {len(embedding)})")
    search_results = await search_pinecone(embedding)
    if not search_results or not search_results.get("matches"):
        return "I couldn't find any product information about that."
    
    # 3. Extract context from matches
    contexts = []
    for i, match in enumerate(search_results["matches"]):
        if "metadata" in match and "text" in match["metadata"]:
            context_text = match["metadata"]["text"]
            contexts.append(context_text)
            logger.info(f"Match #{i+1} (score: {match['score']:.4f}): {context_text[:100]}...")
    
    if not contexts:
        return "I found some matches but couldn't extract useful information."
    
    # 4. Generate response with context
    context = "\n-----------------\n".join(contexts)
    logger.info("3️⃣ Generating response with context...")
    answer = await generate_answer_with_gemini(query, context)
    
    logger.info(f"✅ Generated response: {answer[:100]}...")
    return answer

# HTTP route: When Plivo calls, respond with <Stream> XML
@app.route("/webhook", methods=["GET", "POST"])
async def webhook():
    caller_number = request.args.get('From', 'Unknown')
    logger.info(f"📞 Incoming call from: {caller_number}")
    
    stream_url = f"ws://{request.host}/media-stream"

    xml_data = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Speak voice="Polly.Amy">Welcome! Please ask me about any products you're interested in.</Speak>
        <Stream streamTimeout="86400" keepCallAlive="true" bidirectional="true" contentType="audio/x-mulaw;rate=8000" audioTrack="inbound">
            {stream_url}
        </Stream>
    </Response>
    '''
    return Response(xml_data, mimetype='application/xml')

# WebSocket route: Handle Plivo audio stream
@app.websocket('/media-stream')
async def media_stream():
    logger.info("📞 Plivo client connected")

    plivo_ws = websocket
    
    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    try:
        async with websockets.connect(url, extra_headers=headers) as openai_ws:
            logger.info("✅ Connected to OpenAI real-time API")
            
            # Initialize OpenAI session
            await openai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "turn_detection": {"type": "server_vad"},
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
                    "voice": "alloy",
                    "instructions": SYSTEM_MESSAGE,
                    "modalities": ["text", "audio"],
                    "temperature": 0.7
                }
            }))
            logger.info("✅ OpenAI session initialized")
            
            # NEW: Tell OpenAI to wait for context
            await openai_ws.send(json.dumps({
                "type": "message",
                "message": {
                    "role": "system",
                    "content": "When the user asks about products, wait for additional product information before responding."
                }
            }))
            logger.info("✅ Sent wait instruction to OpenAI")
            
            # Handle bidirectional communication
            plivo_task = asyncio.create_task(handle_plivo_messages(plivo_ws, openai_ws))
            openai_task = asyncio.create_task(handle_openai_messages(openai_ws, plivo_ws))
            
            # Wait for any task to complete
            done, pending = await asyncio.wait(
                [plivo_task, openai_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel other tasks
            for task in pending:
                task.cancel()

    except Exception as e:
        logger.error(f"❌ Error in WebSocket connection: {str(e)}", exc_info=True)
    finally:
        # Reset state
        global current_transcript, speech_in_progress
        current_transcript = ""
        speech_in_progress = False
        response_control.can_respond = False
        response_control.context_updated = False
        logger.info("Session ended, resources cleaned up")

async def handle_plivo_messages(plivo_ws, openai_ws):
    """Handle incoming audio from Plivo and send to OpenAI"""
    try:
        while True:
            message = await plivo_ws.receive()
            data = json.loads(message)

            if data['event'] == 'media' and openai_ws.open:
                # Forward audio to OpenAI
                audio_append = {
                    "type": "input_audio_buffer.append",
                    "audio": data['media']['payload']
                }
                await openai_ws.send(json.dumps(audio_append))

            elif data['event'] == "start":
                logger.info("🎙️ Plivo Audio streaming started")
                plivo_ws.stream_id = data['start']['streamId']

    except websockets.ConnectionClosed:
        logger.info("Plivo connection closed")

async def handle_openai_messages(openai_ws, plivo_ws):
    """Handle responses from OpenAI and send to Plivo"""
    global current_transcript, speech_in_progress, openai_responding, pending_pinecone_query
    
    try:
        async for message in openai_ws:
            response = json.loads(message)

            if response['type'] == 'session.updated':
                logger.info("🔄 OpenAI session updated")
            
            # Handle speech detection
            elif response['type'] == 'input_audio_buffer.speech_started':
                logger.info("🗣️ Speech started")
                speech_in_progress = True
                current_transcript = ""  # Reset transcript for new speech
                # NEW: Reset response control at start of new speech
                async with response_control.response_lock:
                    response_control.can_respond = False
                    response_control.context_updated = False
                response_control.processing_complete.clear()
            
            # Handle transcript updates - CRITICAL PATH
            elif response['type'] == 'input_audio_buffer.transcript.delta':
                transcript_chunk = response.get('delta', {}).get('text', '')
                if transcript_chunk and transcript_chunk.strip():
                    # Update our transcript
                    current_transcript += transcript_chunk
                    logger.info(f"🔤 Transcript updated: '{current_transcript}'")
            
            # Handle end of speech - CRITICAL POINT TO QUERY PINECONE
            elif response['type'] == 'input_audio_buffer.speech_ended':
                speech_in_progress = False
                logger.info(f"💬 Speech ended. Final transcript: '{current_transcript}'")
                
                # NEW: Block OpenAI from responding
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.paused",
                    "paused": True
                }))
                logger.info("⏸️ Paused OpenAI input processing")
                
                # Process with Pinecone before OpenAI responds
                if current_transcript and current_transcript.strip():
                    # Set flag to prevent OpenAI responding before Pinecone completes
                    pending_pinecone_query = True
                    
                    # Process query with Pinecone and Gemini
                    product_info = await process_user_query(current_transcript.strip())
                    
                    if product_info:
                        # Send context to OpenAI
                        context_message = {
                            "type": "assistant.context.update",
                            "context": [
                                {
                                    "text": f"PRODUCT INFORMATION: {product_info}"
                                }
                            ]
                        }
                        
                        logger.info(f"📝 Sending product info to OpenAI: {len(product_info)} chars")
                        await openai_ws.send(json.dumps(context_message))
                        logger.info("✅ Product context sent to OpenAI")
                        
                        # NEW: Mark context as updated
                        response_control.context_updated = True
                    
                    # Reset flag
                    pending_pinecone_query = False
                
                # NEW: Resume OpenAI processing
                await openai_ws.send(json.dumps({
                    "type": "input_audio_buffer.paused",
                    "paused": False
                }))
                logger.info("▶️ Resumed OpenAI input processing")
                
                # NEW: Allow OpenAI to respond
                async with response_control.response_lock:
                    response_control.can_respond = True
                response_control.processing_complete.set()
                logger.info("✅ Processing complete, OpenAI can now respond")
                
                # Reset transcript
                current_transcript = ""
                
                # NEW: Signal to OpenAI that we're ready for response
                await openai_ws.send(json.dumps({
                    "type": "message",
                    "message": {
                        "role": "system",
                        "content": "Pinecone processing complete. You can now respond to the user's query."
                    }
                }))
            
            # Handle OpenAI audio response
            elif response['type'] == 'response.audio.delta':
                # NEW: Wait for Pinecone processing to complete before first audio chunk
                if not openai_responding:
                    # Wait for processing to complete with timeout
                    try:
                        await asyncio.wait_for(response_control.processing_complete.wait(), timeout=5.0)
                        logger.info("✅ Waited for Pinecone processing to complete")
                    except asyncio.TimeoutError:
                        logger.warning("⚠️ Timeout waiting for Pinecone processing, proceeding anyway")
                
                openai_responding = True
                
                # Send audio to Plivo
                audio_delta = {
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                    }
                }
                await plivo_ws.send(json.dumps(audio_delta))
            
            # Handle end of OpenAI response
            elif response['type'] == 'response.complete':
                openai_responding = False
                logger.info("✅ OpenAI response complete")
                # Reset for next turn
                async with response_control.response_lock:
                    response_control.can_respond = False

    except websockets.ConnectionClosed:
        logger.info("OpenAI connection closed")
    except Exception as e:
        logger.error(f"❌ Error handling OpenAI messages: {str(e)}", exc_info=True)

# Debug route to verify system status
@app.route("/debug", methods=["GET"])
async def debug():
    # Generate simple test embedding
    test_embedding = await generate_embedding("test query")
    
    status = {
        "service_status": {
            "gemini_ready": gemini_ready,
            "pinecone_ready": pinecone_ready,
            "embedding_generation_works": test_embedding is not None
        },
        "speech_in_progress": speech_in_progress,
        "current_transcript": current_transcript,
        "pending_pinecone_query": pending_pinecone_query,
        "openai_responding": openai_responding,
        "response_control": {
            "can_respond": response_control.can_respond,
            "context_updated": response_control.context_updated
        }
    }
    return Response(json.dumps(status), mimetype='application/json')

# Test route for manual queries
@app.route("/test-query", methods=["POST"])
async def test_query():
    data = await request.get_json()
    query = data.get("query", "")
    
    if not query:
        return Response(json.dumps({"error": "No query provided"}), status=400, mimetype='application/json')
    
    try:
        result = await process_user_query(query)
        return Response(json.dumps({
            "query": query,
            "result": result,
            "success": result is not None
        }), mimetype='application/json')
    except Exception as e:
        logger.error(f"❌ Error in test query: {str(e)}", exc_info=True)
        return Response(json.dumps({
            "error": str(e),
            "query": query,
            "success": False
        }), status=500, mimetype='application/json')

if __name__ == "__main__":
    logger.info(f"🚀 Starting server on port {PORT}...")
    app.run(host="0.0.0.0", port=PORT)