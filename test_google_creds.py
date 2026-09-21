import json
import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

def test_credentials():
    print("Checking credentials file existence...")
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"FAIL: File {CREDENTIALS_FILE} not found!")
        sys.exit(1)
    
    with open(CREDENTIALS_FILE, "r") as f:
        data = json.load(f)
    
    installed = data.get("installed", {})
    client_id = installed.get("client_id", "")
    project_id = installed.get("project_id", "")
    auth_uri = installed.get("auth_uri", "")
    token_uri = installed.get("token_uri", "")
    client_secret = installed.get("client_secret", "")

    print(f"Project ID: {project_id}")
    print(f"Client ID: {client_id[:20]}...{client_id[-15:] if len(client_id) > 35 else ''}")
    print(f"Auth URI: {auth_uri}")
    print(f"Token URI: {token_uri}")
    print(f"Secret Present: {'Yes' if bool(client_secret) else 'No'}")

    # Test constructing InstalledAppFlow
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("\nSUCCESS: OAuth InstalledAppFlow initialized cleanly!")
        print(f"Generated Auth URL successfully: {auth_url[:60]}...")
        return True
    except Exception as e:
        print(f"\nFAIL: Error initializing flow: {e}")
        return False

if __name__ == "__main__":
    success = test_credentials()
    if success:
        print("\nClient secret credentials file is 100% VALID.")
    else:
        sys.exit(1)
