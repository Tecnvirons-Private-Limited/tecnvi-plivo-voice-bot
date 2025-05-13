# RAG search function from example.py
import logging
import google.generativeai as genai
from pinecone import Pinecone
from dotenv import load_dotenv
import os
# Load environment variables
load_dotenv(dotenv_path='.env', override=True)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
print(f"INDEX_NAME: {INDEX_NAME}")
# Set up Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)
try:
    index = pc.Index(INDEX_NAME)
    logger.info(f"Connected to Pinecone index: {INDEX_NAME}")
except Exception as e:
    logger.error(f"Pinecone setup error: {e}")
    raise

async def search_product_database(query, namespace=os.getenv("DEFAULT_NAMESPACE")):
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
            top_k=3,
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

        Extract the product information from any "Unnamed" labels, then respond in a natural, conversational tone as if you're speaking to someone. Include:
        - The product name (from the first "Unnamed" field)
        - The quantity (the number after a date range)
        - The unit price
        - The total cost

        For example, if you see:
        "Unnamed: 0: BOLT ALLEN M6X10LX1P RH SS 202
        1-Apr-24 to 1-Mar-25: 100
        Unnamed: 2: 9.86
        Unnamed: 3: 985.64"

        Respond conversationally like:
        "I found that BOLT ALLEN M6X10LX1P RH SS is available. You can get 100 units at ₹9.86 each, with a total cost of ₹985.64. Is there anything specific about this product you'd like to know?"

        Maintain a helpful, friendly tone and address the user's question: {query}
        If the question asks for specific information, focus on that part in your response.
        Note: IF the product number is negative or any NAN values just say it is out of stock.
        Also the currency is in INR.
        """

        summary = genai.GenerativeModel("gemini-1.5-flash").generate_content(summary_prompt)
        return summary.text

    except Exception as e:
        logger.error(f"Vector search error: {e}")
        return f"Sorry, I encountered an error searching our product database."
