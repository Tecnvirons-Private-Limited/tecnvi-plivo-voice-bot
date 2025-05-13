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

def send_templated_message(recipient_number, url):
    url = url.replace("https://","")
    """
    Sends a WhatsApp message using a predefined template with recipient's name in the header.
    
    Args:
        recipient_name (str): Name to display in the message header
        recipient_number (str): Recipient's WhatsApp number with country code
    """
    # Define the template structure
    template = Template(**{
        "name": "pdf_integration_template",  # Template name
        "language": "en",
        "components": [
    	{
    		"type": "body",
    		"parameters": [
              {
                        "type": "text",
                        "text": url
                    }
    		]
    	}]
    })

    # Send the WhatsApp message with the template
    response = client.messages.create(
        src="+15557282843",  # Your Plivo WhatsApp-enabled number
        dst=recipient_number,  # Recipient's WhatsApp number
        type_="whatsapp",
        template=template,
    )
    print("Message UUID:", response)

def send_simple_whatsapp(recipient_number, message_text):
    client.messages.create(
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
            - If quantity or price is not available , dont show the item in the invoice.
            - At the end, add a line with the **Total Payable Amount** summing only the items with valid total prices.
            - ALWAYS include a separate and prominent section clearly showing APPOINTMENT details if present.
            - Look for information under "APPOINTMENT BOOKING", "APPOINTMENT SUMMARY", or "CALENDAR QUERY" sections.
            - If appointments are found, format them clearly with date, time, and status.
            - Keep the tone polite and informative.
            - Keep message with proper line breaks and spaces as this response will be converted into pdf format.
            - Include today's date as `{today}`.
            - If no transcript is available, just say "Thankyou for the call"
            - Do not include symbols like ₹ or $ in the invoice. Just use INR.
            Here is the input:

            {transcript_and_queries}

            Generate output in this format:

            Product Inquiry Summary  
            Date: [Date]

            Requested Items: [List of general items, e.g., Bearings, Impellers]

            S.No   Product Name               Quantity    Unit Price    Total Price  
            1      [Product Name]             [Qty]       [INR]           [INR]  
            2      [Product Name]             [Qty]       [INR]           [INR]  
            ...  

            💵 Total Estimated Cost: ₹[total]

            APPOINTMENT DETAILS (if any):
            Date: [Date]
            Time: [Time]
            Status: [Confirmed/Pending]
            
            No need to provide the calender link.
            Note: This is only a summary of product inquiries. Let us know if you'd like to proceed or have any other questions.
            Thank you for your inquiry!
"""

    # Use Gemini instead of OpenAI
    response = genai.GenerativeModel("gemini-1.5-flash").generate_content(prompt)
    
    return response.text