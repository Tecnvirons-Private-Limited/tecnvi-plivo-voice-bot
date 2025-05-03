We are stuck with the issue where we need the flow to be like openai transcribed text must go to genai where it is embedded and then that embedded text is passed on pinecone which generates proper product qeury and then that product query is answered using openai. But the problem we are facing is that while we are able to connect to the call but our code flow dont goes through pinecone like the query is handled directly by openai and sometimes call also get cut if delay is added. The flow directly goes on with openai than using genai embedding and pinecone vector db. Please look out in the code and help us with your valuable suggestions. For your more information these are the logs.


PS D:\realtime-voice-bot> python app.py
2025-05-03 09:25:46,277 - __main__ - INFO - Configuring Gemini API...
2025-05-03 09:25:49,080 - __main__ - INFO - Gemini test response: Yes, I am working.  I'm ready to assist you with y...
2025-05-03 09:25:49,087 - __main__ - INFO - ✅ Gemini API confirmed working
2025-05-03 09:25:49,089 - __main__ - INFO - Initializing Pinecone client...
2025-05-03 09:25:50,449 - __main__ - INFO - Available Pinecone indexes: ['voice-bot-gemini-embedding-004-index', 'voice-bot-product-index', 'voice-bot-for-auto-upload-files-gem-emb']
2025-05-03 09:25:50,449 - __main__ - INFO - ✅ Using existing Pinecone index: voice-bot-gemini-embedding-004-index
2025-05-03 09:25:52,259 - __main__ - INFO - Pinecone index stats: {'dimension': 768,
 'index_fullness': 0.0,
 'metric': 'cosine',
 'namespaces': {'1jneYkYspw4Fh1e0ewgLcvZviukmn5v-iwioaV7Wm8rk-20250502122822': {'vector_count': 3},
                '1jneYkYspw4Fh1e0ewgLcvZviukmn5v-iwioaV7Wm8rk-20250502122854': {'vector_count': 3},
                '1jneYkYspw4Fh1e0ewgLcvZviukmn5v-iwioaV7Wm8rk-20250502130157': {'vector_count': 3},
                '1jneYkYspw4Fh1e0ewgLcvZviukmn5v-iwioaV7Wm8rk-20250502130514': {'vector_count': 4},
                '1jneYkYspw4Fh1e0ewgLcvZviukmn5v-iwioaV7Wm8rk-20250502135300': {'vector_count': 4},
                '1jneYkYspw4Fh1e0ewgLcvZviukmn5v-iwioaV7Wm8rk-20250502150601': {'vector_count': 4},
                'Tec Nviirons Sample data testing.xlsx 2025-05-02 09:05:24': {'vector_count': 314},
                'gsheet_namespace': {'vector_count': 4}},
 'total_vector_count': 339,
 'vector_type': 'dense'}
2025-05-03 09:25:52,259 - __main__ - INFO - ✅ Pinecone index connection confirmed
2025-05-03 09:25:52,264 - __main__ - INFO - 🚀 Starting server on port 5000...
2025-05-03 09:25:52,267 - asyncio - DEBUG - Using proactor: IocpProactor
 * Serving Quart app 'app'
 * Debug mode: False
 * Please use an ASGI server (e.g. Hypercorn) directly in production
 * Running on http://0.0.0.0:5000 (CTRL + C to quit)
[2025-05-03 09:25:52 +0530] [3672] [INFO] Running on http://0.0.0.0:5000 (CTRL + C to quit)
2025-05-03 09:25:52,373 - hypercorn.error - INFO - Running on http://0.0.0.0:5000 (CTRL + C to quit)
2025-05-03 09:26:20,661 - __main__ - INFO - 📞 Incoming call from: Unknown
[2025-05-03 09:26:20 +0530] [3672] [INFO] 127.0.0.1:51084 POST /webhook 1.1 200 401 2444
2025-05-03 09:26:25,882 - __main__ - INFO - 📞 Plivo client connected
2025-05-03 09:26:27,137 - __main__ - INFO - ✅ Connected to OpenAI real-time API
2025-05-03 09:26:27,140 - __main__ - INFO - ✅ OpenAI session initialized
2025-05-03 09:26:27,140 - __main__ - INFO - ✅ Sent wait instruction to OpenAI
[2025-05-03 09:26:27 +0530] [3672] [INFO] 127.0.0.1:51086 GET /media-stream 1.1 101 - 1260565
2025-05-03 09:26:27,170 - __main__ - INFO - 🎙️ Plivo Audio streaming started
2025-05-03 09:26:27,407 - __main__ - INFO - 🔄 OpenAI session updated
2025-05-03 09:26:37,439 - __main__ - INFO - Session ended, resources cleaned up

