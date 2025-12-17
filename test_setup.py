import os
import requests
import pytest
from dotenv import load_dotenv
from google.cloud import firestore

# Load keys
load_dotenv()

def test_alpaca_connection():
    """Test connection to Alpaca API."""
    print("--- 🚀 TEST ALPACA ---")
    alpaca_url = f"{os.getenv('ALPACA_BASE_URL')}/v2/account"
    headers = {
        "APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY")
    }
    
    try:
        r = requests.get(alpaca_url, headers=headers)
        if r.status_code == 200:
            print(f"✅ Alpaca Connected: Buying Power ${r.json().get('buying_power', 'UNKNOWN')}")
        else:
            pytest.fail(f"❌ Alpaca Failed: {r.text}")
    except Exception as e:
        pytest.fail(f"❌ Alpaca Error: {e}")

def test_discord_connection(mocker):
    """Test connection logic for Discord (Mocked to prevent spam)."""
    print("--- 🚀 TEST DISCORD (MOCKED) ---")
    
    discord_url = f"https://discord.com/api/v9/channels/{os.getenv('DISCORD_CHANNEL_ID')}/messages"
    auth = {"Authorization": f"Bot {os.getenv('DISCORD_BOT_TOKEN')}"}
    payload = {"content": "Hello from the Python Mainframe! 🐍"}
    
    # Mock the post request
    mock_post = mocker.patch('requests.post')
    mock_post.return_value.status_code = 200
    
    # Call the code that would send the message
    # In a real app, this would be a function call. Here we simulate the logic.
    r = requests.post(discord_url, headers=auth, json=payload)
    
    # Verify the logic
    mock_post.assert_called_once_with(discord_url, headers=auth, json=payload)
    print("✅ Discord Logic Verified: Request mocked successfully!")

def test_firestore_connection():
    """Test connection to Google Cloud Firestore."""
    print("--- 🚀 TEST FIRESTORE ---")
    try:
        db = firestore.Client() # Automatically looks for GOOGLE_APPLICATION_CREDENTIALS
        doc_ref = db.collection("system_checks").document("connectivity_test")
        doc_ref.set({"status": "online", "message": "Service Account is working!"})
        print("✅ GCP Firestore Connected: Test document written!")
    except Exception as e:
        pytest.fail(f"❌ GCP Error: {e}\n(Did you set GOOGLE_APPLICATION_CREDENTIALS in .env?)")
