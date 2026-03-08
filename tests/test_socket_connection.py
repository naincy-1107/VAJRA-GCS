#!/usr/bin/env python3
"""
Test Socket.IO connection and telemetry emission
"""

import socketio
import time
import requests
import json

def test_socket_connection():
    """Test Socket.IO connection to the backend"""
    print("🧪 Testing Socket.IO connection...")
    
    # Create Socket.IO client
    sio = socketio.Client()
    
    @sio.event
    def connect():
        print("✅ Socket.IO connected successfully!")
        print(f"📡 Socket ID: {sio.sid}")
        
        # Request telemetry data
        sio.emit('telemetry_request')
        print("📤 Sent telemetry_request")
    
    @sio.event
    def disconnect():
        print("❌ Socket.IO disconnected")
    
    @sio.event
    def telemetry(data):
        print("📡 Received telemetry data:")
        print(f"   Team ID: {data.get('team_id', 'N/A')}")
        print(f"   Packet Counter: {data.get('packet_counter', 'N/A')}")
        print(f"   Altitude: {data.get('altitude_agl', 'N/A')}m")
        print(f"   Status: {data.get('status', 'N/A')}")
        print(f"   Data keys: {list(data.keys())}")
    
    try:
        # Connect to the backend
        print("🔌 Connecting to http://127.0.0.1:5000...")
        sio.connect('http://127.0.0.1:5000')
        
        # Wait for connection and data
        time.sleep(2)
        
        # Send test telemetry via HTTP
        print("🧪 Sending test telemetry via HTTP...")
        response = requests.post(
            'http://127.0.0.1:5000/api/test_telemetry',
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Test telemetry sent: {result}")
        else:
            print(f"❌ Test telemetry failed: {response.status_code}")
        
        # Wait for telemetry data
        print("⏳ Waiting for telemetry data...")
        time.sleep(5)
        
        # Disconnect
        sio.disconnect()
        print("🔌 Disconnected from Socket.IO")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if sio.connected:
            sio.disconnect()

def test_http_endpoints():
    """Test HTTP endpoints"""
    print("\n🌐 Testing HTTP endpoints...")
    
    # Test ports endpoint
    try:
        response = requests.get('http://127.0.0.1:5000/api/ports')
        if response.status_code == 200:
            ports = response.json()
            print(f"✅ Available ports: {ports}")
        else:
            print(f"❌ Ports endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing ports endpoint: {e}")
    
    # Test telemetry endpoint
    try:
        response = requests.post(
            'http://127.0.0.1:5000/api/test_telemetry',
            headers={'Content-Type': 'application/json'}
        )
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Test telemetry endpoint: {result}")
        else:
            print(f"❌ Test telemetry endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing telemetry endpoint: {e}")

if __name__ == "__main__":
    print("🚀 Socket.IO Connection Test")
    print("=" * 50)
    
    # Test HTTP endpoints first
    test_http_endpoints()
    
    # Test Socket.IO connection
    test_socket_connection()
    
    print("\n✅ Test completed!") 