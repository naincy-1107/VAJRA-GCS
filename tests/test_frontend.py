#!/usr/bin/env python3
"""
Test the frontend by opening it in a browser and checking Socket.IO connection
"""

import webbrowser
import time
import requests
import subprocess
import sys

def test_frontend():
    """Test the frontend by opening it in a browser"""
    print("🧪 Testing Frontend Connection...")
    
    # Test if the HTTP server is running
    try:
        response = requests.get('http://127.0.0.1:8081/index.html', timeout=5)
        if response.status_code == 200:
            print("✅ Frontend server is accessible")
        else:
            print(f"❌ Frontend server returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Frontend server not accessible: {e}")
        return False
    
    # Test if the backend is running
    try:
        response = requests.get('http://127.0.0.1:5000/api/ports', timeout=5)
        if response.status_code == 200:
            print("✅ Backend server is accessible")
        else:
            print(f"❌ Backend server returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Backend server not accessible: {e}")
        return False
    
    # Open the frontend in a browser
    print("🌐 Opening frontend in browser...")
    try:
        webbrowser.open('http://127.0.0.1:8081/index.html')
        print("✅ Frontend opened in browser")
    except Exception as e:
        print(f"❌ Could not open browser: {e}")
    
    # Send test telemetry to trigger frontend update
    print("📡 Sending test telemetry...")
    try:
        response = requests.post(
            'http://127.0.0.1:5000/api/test_telemetry',
            headers={'Content-Type': 'application/json'},
            timeout=5
        )
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Test telemetry sent: {result}")
        else:
            print(f"❌ Test telemetry failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error sending test telemetry: {e}")
    
    print("\n📋 Instructions:")
    print("1. Check the browser console for Socket.IO connection messages")
    print("2. Look for '📡 Received telemetry data' messages in the console panel")
    print("3. Click the 'Test Socket.IO' button to manually test the connection")
    print("4. Check if telemetry data appears in the frontend displays")
    
    return True

def main():
    print("🚀 Frontend Connection Test")
    print("=" * 50)
    
    success = test_frontend()
    
    if success:
        print("\n✅ Frontend test completed!")
        print("🔍 Check the browser for real-time telemetry updates")
    else:
        print("\n❌ Frontend test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main() 