import os
from dotenv import load_dotenv
from plivo import RestClient
from plivo.utils.template import Template
import google.generativeai as genai
from datetime import datetime

load_dotenv()

auth_id = os.getenv('PLIVO_AUTH_ID')
auth_token = os.getenv('PLIVO_AUTH_TOKEN')
GENAI_API_KEY = os.getenv("GOOGLE_API_KEY")

# Configure the Gemini API
genai.configure(api_key=GENAI_API_KEY)

client = RestClient(auth_id, auth_token)


def send_simple_whatsapp(recipient_number, message_text):
    response = client.messages.create(
        src="+15557282843",
        dst=recipient_number,
        text=message_text,
        type_="whatsapp"
    )
    # print("Message UUID:", response.message_uuid)


def generate_inquiry_invoice(transcript_and_queries: str):
    today = datetime.now().strftime("%d %B %Y")
    
    prompt = f"""
            You are a helpful assistant.

            Based on the following CALL TRANSCRIPT & DATABASE QUERIES, summarize the user's **inquired products** into a WhatsApp-style **readable invoice-like format**.

            **IMPORTANT NOTES:**
            - The customer has only *inquired* about the items, not purchased them.
            - Format output like a clean product invoice, with quantity, unit price, total price per item (if available).
            - If quantity or price is not available, mention "Not Available".
            - At the end, add a line with the **Total Payable Amount** summing only the items with valid total prices.
            - Keep the tone polite and informative.
            - Keep message mobile-readable (WhatsApp friendly).
            - Include today's date as `{today}`.

            Here is the input:

            {transcript_and_queries}

            Generate output in this format:

            🧾 Product Inquiry Summary  
            Date: [Date]

            Requested Items: [List of general items, e.g., Bearings, Impellers]

            S.No   Product Name               Quantity    Unit Price    Total Price  
            1      [Product Name]             [Qty]       [$]           [$]  
            2      [Product Name]             [Qty]       [$]           [$]  
            ...  

            💵 Total Estimated Cost: $[total]

            💬 Note: This is only a summary of product inquiries. Let us know if you'd like to proceed or have any other questions.

            Thank you for your inquiry!
"""

    # Use Gemini instead of OpenAI
    response = genai.GenerativeModel("gemini-1.5-flash").generate_content(prompt)
    
    return response.text
