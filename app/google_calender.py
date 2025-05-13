import os
import json
import datetime
import pytz
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Load credentials
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON", "{}"))
GOOGLE_TOKEN = json.loads(os.getenv("GOOGLE_TOKEN_JSON", "{}"))

def build_service():
    """Build and return an authenticated Google Calendar service"""
    try:
        creds = Credentials(
            token=GOOGLE_TOKEN.get("token"),
            refresh_token=GOOGLE_TOKEN.get("refresh_token"),
            token_uri=GOOGLE_TOKEN.get("token_uri"),
            client_id=GOOGLE_TOKEN.get("client_id"),
            client_secret=GOOGLE_TOKEN.get("client_secret"),
            scopes=GOOGLE_TOKEN.get("scopes")
        )
        
        return build("calendar", "v3", credentials=creds)
    except RefreshError as e:
        logger.error(f"Error refreshing token: {e}")
        raise
    except Exception as e:
        logger.error(f"Error building Google Calendar service: {e}")
        raise

def get_available_slots_handler():
    """Get available appointment slots for the next 3 days"""
    try:
        service = build_service()
        IST = pytz.timezone('Asia/Kolkata')
        now = datetime.datetime.now(IST)
        
        # Calculate start (current hour, rounded to nearest 30 min) and end (3 days later)
        if now.minute < 30:
            start = now.replace(minute=30, second=0, microsecond=0)
        else:
            start = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            
        end = now + datetime.timedelta(days=3)
        
        # Convert to UTC for API call
        start_utc = start.astimezone(pytz.UTC)
        end_utc = end.astimezone(pytz.UTC)
        
        # Get events from calendar
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_utc.isoformat(),
            timeMax=end_utc.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Process busy slots
        busy_slots = []
        for event in events:
            start_time = event['start'].get('dateTime', event['start'].get('date'))
            end_time = event['end'].get('dateTime', event['end'].get('date'))
            if start_time and end_time:
                busy_slots.append((start_time, end_time))

        # Generate available 30-min slots
        slots = []
        current = start
        while current < end and len(slots) < 20:
            # Only consider slots during business hours (9 AM to 6 PM)
            if 9 <= current.hour < 18:
                slot_start = current
                slot_end = current + datetime.timedelta(minutes=30)

                # Check for overlap with existing events
                overlap = False
                for bs in busy_slots:
                    bs_start = datetime.datetime.fromisoformat(bs[0].replace('Z', '+00:00'))
                    bs_end = datetime.datetime.fromisoformat(bs[1].replace('Z', '+00:00'))
                    if slot_start < bs_end.astimezone(IST) and slot_end > bs_start.astimezone(IST):
                        overlap = True
                        break

                # Add slot if no overlap and starts at 0 or 30 minutes past the hour
                if not overlap and slot_start.minute in [0, 30]:
                    formatted_start = slot_start.strftime("%Y-%m-%dT%H:%M:%S")
                    formatted_end = slot_end.strftime("%Y-%m-%dT%H:%M:%S")
                    # Make display time more user-friendly
                    display_time = slot_start.strftime("%A, %B %d at %I:%M %p")
                    
                    slots.append({
                        "start": formatted_start,
                        "end": formatted_end,
                        "display_time": display_time
                    })

            # Move to next 30-minute slot
            current += datetime.timedelta(minutes=30)

        logger.info(f"Found {len(slots)} available slots")
        return slots
        
    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return {"error": f"Calendar service error: {error._get_reason()}"}
    except Exception as e:
        logger.error(f"Error fetching available slots: {e}")
        return {"error": f"Failed to fetch available slots: {str(e)}"}

def is_slot_available(proposed_time_str):
    """Check if a specific time slot is available"""
    try:
        service = build_service()
        IST = pytz.timezone('Asia/Kolkata')
        
        # Handle potential formatting issues
        try:
            proposed_time = datetime.datetime.fromisoformat(proposed_time_str)
            if proposed_time.tzinfo is None:
                proposed_time = IST.localize(proposed_time)
        except ValueError:
            logger.error(f"Invalid time format: {proposed_time_str}")
            return False
            
        end_time = proposed_time + datetime.timedelta(minutes=30)
        
        # Convert to UTC for API call
        utc_start = proposed_time.astimezone(pytz.UTC).isoformat()
        utc_end = end_time.astimezone(pytz.UTC).isoformat()
        
        # Only allow booking during business hours (9 AM to 6 PM)
        if not (9 <= proposed_time.hour < 18):
            logger.info(f"Time {proposed_time_str} is outside business hours")
            return False
            
        # Check if slot is in the past
        if proposed_time < datetime.datetime.now(IST):
            logger.info(f"Time {proposed_time_str} is in the past")
            return False

        # Check calendar for conflicts
        events_result = service.events().list(
            calendarId='primary',
            timeMin=utc_start,
            timeMax=utc_end,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        return len(events) == 0  # True if no events → slot is available
        
    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return False
    except Exception as e:
        logger.error(f"Error checking slot availability: {e}")
        return False

def book_slot_handler(start_time_str, email):
    """Book an appointment slot"""
    try:
        service = build_service()
        IST = pytz.timezone('Asia/Kolkata')
        
        # Handle potential formatting issues
        try:
            start_time = datetime.datetime.fromisoformat(start_time_str)
            if start_time.tzinfo is None:
                start_time = IST.localize(start_time)
        except ValueError:
            logger.error(f"Invalid time format: {start_time_str}")
            return {"error": "Invalid time format. Please use YYYY-MM-DDTHH:MM:SS"}
            
        end_time = start_time + datetime.timedelta(minutes=30)

        # Validate the email address
        if not email or '@' not in email:
            email = "customer@example.com"  # Use default if invalid

        # Validation checks
        if start_time < datetime.datetime.now(IST):
            logger.info(f"Attempted to book past time: {start_time_str}")
            return {"error": "Requested time is in the past. Try another slot."}

        # Only allow booking during business hours (9 AM to 6 PM)
        if not (9 <= start_time.hour < 18):
            logger.info(f"Time {start_time_str} is outside business hours")
            return {"error": "Requested time is outside business hours (9 AM to 6 PM). Try another slot."}

        # Check availability
        if not is_slot_available(start_time_str):
            logger.info(f"Slot {start_time_str} is not available")
            return {"error": "Slot is not available. Please choose another time."}

        # Create calendar event
        event = {
            'summary': 'Scheduled Appointment',
            'description': 'Appointment booked through voice bot',
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
            'attendees': [{'email': email}],
            'reminders': {'useDefault': True},
        }

        created_event = service.events().insert(calendarId='primary', body=event, sendUpdates='all').execute()
        logger.info(f"Successfully booked appointment at {start_time_str}")
        
        # Return the event details including link
        return {
            "success": "Appointment booked successfully", 
            "time": start_time.strftime("%A, %B %d at %I:%M %p"),
            "htmlLink": created_event.get('htmlLink', '')
        }
        
    except HttpError as error:
        logger.error(f"Google Calendar API error: {error}")
        return {"error": f"Calendar service error: {error._get_reason()}"}
    except Exception as e:
        logger.error(f"Error booking slot: {e}")
        return {"error": f"Failed to book appointment: {str(e)}"}

# Remove test code that runs on import
if __name__ == "__main__":
    # Only run when file is executed directly
    print("Testing calendar functions:")
    print("Available slots:", get_available_slots_handler())

