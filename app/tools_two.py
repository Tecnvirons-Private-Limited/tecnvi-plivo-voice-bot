import os
from dotenv import load_dotenv
import requests
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from supabase import create_client

# Load environment variables
load_dotenv()

# Initialize Supabase client with service role key to bypass RLS
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Using service role key instead of anon key
supabase = create_client(supabase_url, supabase_key)

# Bucket name constant
BUCKET_NAME = "profiles"

def ensure_bucket_exists(bucket_name):
    """Check if bucket exists, create if it doesn't, and ensure it's public"""
    try:
        # List all buckets to check if our bucket exists
        buckets = supabase.storage.list_buckets()
        bucket_exists = any(bucket.name == bucket_name for bucket in buckets)
        
        if not bucket_exists:
            print(f"Bucket '{bucket_name}' not found. Creating it...")
            # Create the bucket with public access
            supabase.storage.create_bucket(bucket_name, {"public": True})
            print(f"Bucket '{bucket_name}' created successfully.")
        else:
            print(f"Bucket '{bucket_name}' already exists.")
            
            # Ensure the bucket is public
            supabase.storage.update_bucket(bucket_name, {"public": True})
            print(f"Updated '{bucket_name}' bucket to be public.")
            
        return True
    except Exception as e:
        print(f"Error managing bucket: {str(e)}")
        if hasattr(e, 'response'):
            print(f"Response details: {e.response.text if hasattr(e.response, 'text') else e.response}")
        return False

# def create_pdf():
#     """Create a PDF with the provided template content"""
#     # Store the text content in a variable as requested
#     pdf_content = """🧾 Product Inquiry Summary  
#             Date: [Date]

#             Requested Items: [List of general items, e.g., Bearings, Impellers]

#             S.No   Product Name               Quantity    Unit Price    Total Price  
#             1      [Product Name]             [Qty]       [$]           [$]  
#             2      [Product Name]             [Qty]       [$]           [$]  
#             ...  

#             💵 Total Estimated Cost: $[total]

#             💬 Note: This is only a summary of product inquiries. Let us know if you'd like to proceed or have any other questions.

#             Thank you for your inquiry!"""
    
#     # Create PDF
#     buffer = io.BytesIO()
#     doc = SimpleDocTemplate(buffer, pagesize=letter)
#     styles = getSampleStyleSheet()
    
#     # Create content element
#     elements = []
#     for line in pdf_content.split('\n'):
#         elements.append(Paragraph(line, styles['Normal']))
#         elements.append(Spacer(1, 6))
    
#     # Build the PDF
#     doc.build(elements)
#     buffer.seek(0)
#     return buffer

# def upload_pdf_and_get_short_url():
#     """Upload PDF to Supabase and return shortened URL"""
#     try:
#         # Ensure the bucket exists and is public
#         if not ensure_bucket_exists(BUCKET_NAME):
#             return None
            
#         # Create PDF
#         pdf_buffer = create_pdf()
        
#         # Generate a unique filename
#         filename = f"inquiry_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        
#         # Upload the file to Supabase
#         result = supabase.storage.from_(BUCKET_NAME).upload(
#             path=filename,
#             file=pdf_buffer.getvalue(),
#             file_options={"content-type": "application/pdf"}
#         )
#         print(f"Upload result: {result}")
        
#         # Get public URL that doesn't expire
#         pdf_url = supabase.storage.from_(BUCKET_NAME).get_public_url(filename)
#         print(f"Generated URL: {pdf_url}")
        
#         # Test the URL to make sure it's accessible
#         test_response = requests.head(pdf_url)
#         if test_response.status_code >= 400:
#             print(f"Warning: The URL may not be accessible. Status code: {test_response.status_code}")
        
#         # Shorten URL using CleanURI API
#         shorten_response = requests.post(
#             "https://cleanuri.com/api/v1/shorten",
#             data={"url": pdf_url},
#         )
        
#         # Return the shortened URL
#         if shorten_response.status_code == 200:
#             return shorten_response.json().get("result_url")
#         else:
#             print(f"Error shortening URL: {shorten_response.text}")
#             return pdf_url  # Return original URL if shortening fails
    
#     except Exception as e:
#         print(f"Error occurred: {str(e)}")
#         if hasattr(e, 'response'):
#             print(f"Response details: {e.response.text if hasattr(e.response, 'text') else e.response}")
#         return None


def upload_text_to_pdf_and_get_short_url(text_content, filename_prefix="document"):
    """
    Convert text to PDF, upload to Supabase, and return shortened URL
    
    Args:
        text_content (str): The text content to include in the PDF
        filename_prefix (str, optional): Prefix for the generated filename. Defaults to "document".
        
    Returns:
        str: Shortened URL for the uploaded PDF, or None if an error occurs
    """
    try:
        # Ensure the bucket exists and is public
        if not ensure_bucket_exists(BUCKET_NAME):
            return None
            
        # Create PDF from provided text
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        
        # Create content elements
        elements = []
        for line in text_content.split('\n'):
            elements.append(Paragraph(line, styles['Normal']))
            elements.append(Spacer(1, 6))
        
        # Build the PDF
        doc.build(elements)
        buffer.seek(0)
        
        # Generate a unique filename
        filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        
        # Upload the file to Supabase
        result = supabase.storage.from_(BUCKET_NAME).upload(
            path=filename,
            file=buffer.getvalue(),
            file_options={"content-type": "application/pdf"}
        )
        print(f"Upload result: {result}")
        
        # Get public URL that doesn't expire
        pdf_url = supabase.storage.from_(BUCKET_NAME).get_public_url(filename)
        print(f"Generated URL: {pdf_url}")
        
        # Test the URL to make sure it's accessible
        test_response = requests.head(pdf_url)
        if test_response.status_code >= 400:
            print(f"Warning: The URL may not be accessible. Status code: {test_response.status_code}")
        
        # Shorten URL using CleanURI API
        shorten_response = requests.post(
            "https://cleanuri.com/api/v1/shorten",
            data={"url": pdf_url},
        )
        
        # Return the shortened URL
        if shorten_response.status_code == 200:
            return shorten_response.json().get("result_url")
        else:
            print(f"Error shortening URL: {shorten_response.text}")
            return pdf_url  # Return original URL if shortening fails
    
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        if hasattr(e, 'response'):
            print(f"Response details: {e.response.text if hasattr(e.response, 'text') else e.response}")
        return None

# # Example usage
# text = """Sample Report
# Date: May 11, 2025

# This is a sample text that will be converted to PDF,
# uploaded to Supabase, and shared via a shortened URL.

# Thank you!"""

# url = upload_text_to_pdf_and_get_short_url(text, "report")
# if url:
#     print(f"Your document is available at: {url}")
# else:
#     print("Failed to generate document URL")