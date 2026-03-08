#!/usr/bin/env python3
"""
Test script to verify TX port functionality
This script tests the TX port connection and data transmission to /dev/ttyACM0 at 19200 baud
"""

import serial
import struct
import time
import sys

def create_test_packet():
    """Create a test telemetry packet"""
    packet = bytearray()
    
    # Start delimiter
    packet.append(0xFF)
    packet.append(0xFF)
    
    # Team ID and packet counter
    packet.append(142)  # Team ID
    packet.append(1)    # Packet counter
    
    # Test data (floats)
    test_values = [
        100.5,    # altitude_agl
        41.015234, # rocket_latitude
        28.979530, # rocket_longitude
        120.3,    # rocket_gps_altitude
        41.015240, # payload_latitude
        28.979535, # payload_longitude
        115.7,    # payload_gps_altitude
        0.5,      # gyro_x
        -0.3,     # gyro_y
        0.8,      # gyro_z
        0.1,      # accel_x
        -0.2,     # accel_y
        -9.81,    # accel_z
        15.5,     # angle
    ]
    
    # Pack all float values
    for value in test_values:
        packet.extend(struct.pack('<f', value))
    
    # Status code
    packet.append(2)  # Status code
    
    # Calculate checksum
    checksum = 0
    for i in range(2, len(packet)):  # From team_id to status_code
        checksum ^= packet[i]
    packet.append(checksum)
    
    # End delimiter
    packet.append(0x0D)
    packet.append(0x0A)
    
    return bytes(packet)

def create_simple_test_packet():
    """Create a simple test packet"""
    packet = bytearray()
    
    # Header
    packet.append(0xAB)
    
    # 8 float values (32 bytes)
    values = [
        100.5,    # altitude
        1001.25,  # pressure
        0.1,      # accel_x
        -0.2,     # accel_y
        -1.0,     # accel_z
        0.5,      # gyro_x
        -0.3,     # gyro_y
        15.5,     # angle
    ]
    
    for value in values:
        packet.extend(struct.pack('<f', round(value, 2)))
    
    # Checksum
    checksum = sum(packet[1:]) % 256
    packet.append(checksum)
    
    # Footer
    packet.append(0x0D)
    packet.append(0x0A)
    
    return bytes(packet)

def test_tx_port():
    """Test TX port connection and data transmission"""
    port = "/dev/ttyACM0"
    baud = 19200
    
    print(f"🔌 Testing TX port connection to {port} @ {baud} baud...")
    
    try:
        # Try to connect to the port
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        
        print(f"✅ Successfully connected to {port}")
        
        # Test 1: Send simple packet
        print("\n📤 Test 1: Sending simple packet...")
        simple_packet = create_simple_test_packet()
        ser.write(simple_packet)
        ser.flush()
        print(f"✅ Sent simple packet ({len(simple_packet)} bytes)")
        
        # Show packet contents
        packet_hex = ' '.join([f"{b:02X}" for b in simple_packet])
        print(f"📦 Packet: {packet_hex}")
        
        time.sleep(0.5)
        
        # Test 2: Send full packet
        print("\n📤 Test 2: Sending full packet...")
        full_packet = create_test_packet()
        ser.write(full_packet)
        ser.flush()
        print(f"✅ Sent full packet ({len(full_packet)} bytes)")
        
        # Show packet contents
        packet_hex = ' '.join([f"{b:02X}" for b in full_packet[:20]])
        print(f"📦 Packet: {packet_hex}...")
        
        time.sleep(0.5)
        
        # Test 3: Send multiple packets
        print("\n📤 Test 3: Sending multiple packets...")
        for i in range(5):
            # Update packet counter
            full_packet = create_test_packet()
            full_packet = bytearray(full_packet)
            full_packet[3] = i + 1  # Update packet counter
            
            ser.write(bytes(full_packet))
            ser.flush()
            print(f"✅ Sent packet {i+1}/5")
            time.sleep(0.1)
        
        print("\n✅ All tests completed successfully!")
        print(f"📊 Sent packets to {port} @ {baud} baud")
        
        ser.close()
        return True
        
    except serial.SerialException as e:
        print(f"❌ Serial connection failed: {e}")
        print("💡 Make sure:")
        print("   - The device is connected to /dev/ttyACM0")
        print("   - You have permission to access the port")
        print("   - The port is not being used by another application")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def list_available_ports():
    """List all available serial ports"""
    import serial.tools.list_ports
    
    print("🔍 Available serial ports:")
    ports = serial.tools.list_ports.comports()
    
    if not ports:
        print("   No serial ports found")
        return
    
    for port in ports:
        print(f"   {port.device}: {port.description}")
        if port.hwid:
            print(f"      Hardware ID: {port.hwid}")

if __name__ == "__main__":
    print("🧪 TX Port Test Script")
    print("=" * 50)
    
    # List available ports first
    list_available_ports()
    print()
    
    # Test TX port
    success = test_tx_port()
    
    if success:
        print("\n🎉 TX port test PASSED!")
        sys.exit(0)
    else:
        print("\n💥 TX port test FAILED!")
        sys.exit(1) 