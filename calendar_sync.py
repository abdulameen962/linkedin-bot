import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import db

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.readonly"
]

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")

def get_calendar_service():
    """
    Initializes and returns an authorized Google Calendar API service instance.
    Uses token.json if available, or starts InstalledAppFlow using credentials.json.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"[WARN] [calendar_sync] Error loading token file: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"[WARN] [calendar_sync] Could not refresh credentials: {e}")
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(f"Google credentials file '{CREDENTIALS_FILE}' not found!")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for future runs
        with open(TOKEN_FILE, "w") as token_f:
            token_f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

def sync_google_calendar_events(days_back: int = 7, days_forward: int = 30) -> Dict[str, Any]:
    """
    Fetches calendar events in the given window, matches attendees/titles
    against the leads database, and flags booked calls.
    """
    try:
        service = get_calendar_service()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not authenticate with Google Calendar: {str(e)}",
            "matched_leads": []
        }

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_back)).isoformat()
    time_max = (now + timedelta(days=days_forward)).isoformat()

    try:
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to list Google Calendar events: {str(e)}",
            "matched_leads": []
        }

    matched_leads = []
    
    for event in events:
        event_id = event.get("id")
        summary = event.get("summary", "")
        description = event.get("description", "")
        start_time = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        meet_link = event.get("hangoutLink", "")
        
        attendees = event.get("attendees", [])
        attendee_emails = [a.get("email", "").lower() for a in attendees if a.get("email")]
        attendee_names = [a.get("displayName", "") for a in attendees if a.get("displayName")]

        # Match against our database
        lead = None

        # 1. Match by attendee emails
        for email in attendee_emails:
            lead = db.find_lead_by_name_or_email(name="", email=email)
            if lead:
                break

        # 2. Match by attendee display names
        if not lead:
            for name in attendee_names:
                lead = db.find_lead_by_name_or_email(name=name)
                if lead:
                    break

        # 3. Match from event summary (e.g. "Ascentrader Discovery: Alex Vance")
        if not lead and summary:
            # Check if any lead's name is in summary
            for word in summary.split():
                if len(word) >= 3:
                    potential_lead = db.find_lead_by_name_or_email(name=word)
                    if potential_lead:
                        lead = potential_lead
                        break

        if lead:
            profile_url = lead["profile_url"]
            full_name = lead["full_name"]
            
            # If not yet marked or details updated
            if not lead.get("call_booked"):
                db.mark_call_booked(
                    profile_url=profile_url,
                    event_id=event_id,
                    email=attendee_emails[0] if attendee_emails else None,
                    booked_at=start_time
                )
                matched_leads.append({
                    "name": full_name,
                    "profile_url": profile_url,
                    "summary": summary,
                    "start_time": start_time,
                    "meet_link": meet_link,
                    "newly_marked": True
                })
            else:
                matched_leads.append({
                    "name": full_name,
                    "profile_url": profile_url,
                    "summary": summary,
                    "start_time": start_time,
                    "meet_link": meet_link,
                    "newly_marked": False
                })

    return {
        "status": "success",
        "total_events_scanned": len(events),
        "matched_count": len(matched_leads),
        "matched_leads": matched_leads,
        "synced_at": now.strftime("%Y-%m-%d %H:%M:%S UTC")
    }

if __name__ == "__main__":
    print("Testing Google Calendar Sync...")
    res = sync_google_calendar_events()
    print("Sync Result:", json.dumps(res, indent=2))
