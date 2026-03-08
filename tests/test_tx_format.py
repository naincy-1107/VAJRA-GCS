#!/usr/bin/env python3
"""
Test script to verify TX packet format matches txCheck.py
"""

import struct
import sys
import os

# Add the current directory to path to import rxbackend functions
sys.path.append('.')

# Import the TX packet creation functions
from rxbackend import create_tx_packet, create_simple_tx_packet

def float_to_bytes(value):
    """Convert float to 4-byte little endian format."""
    return struct.pack('<f', value)

def calculate_checksum_txcheck(packet_bytes):
    """Checksum = sum of bytes from Byte 5 to Byte 75, mod 256"""
    return sum(packet_bytes[4:75]) % 256

def generate_txcheck_packet(counter):
    """Generate a valid 78-byte packet using txCheck.py format."""
    packet = bytearray()

    # Header
    packet += bytearray([0xFF, 0xFF, 0x54, 0x52])

    # Byte 5: Team ID
    packet.append(142)  # Team ID

    # Byte 6: Packet counter (0-255)
    packet.append(counter % 256)

    # 17 float values (68 bytes)
    float_fields = [
        1238.1, 1240.1, 41.015236, 28.979540,  # altitude, gps_alt, lat, lon
        115.7, 41.015240, 28.979535,  # payload data
        110.2, 41.015230, 28.979525,  # stage data
        0.26, -0.11, 0.61,  # gyro x,y,z
        -0.09, 0.10, -0.90,  # accel x,y,z
        15.8  # angle
    ]

    # Convert float values to bytes
    for f in float_fields:
        packet += float_to_bytes(f)

    # Byte 74: Status (1-4)
    status = 4
    packet.append(status)

    # Byte 75: Checksum
    checksum = calculate_checksum_txcheck(packet)
    packet.append(checksum)

    # Footer: Byte 76, 77
    packet += bytearray([0x0D, 0x0A])

    return packet

def test_packet_formats():
    """Test that both packet formats generate identical results."""
    print("🧪 Testing TX packet format compatibility...")
    
    # Test data
    test_data = {
        "team_id": 142,
        "packet_counter": 4,
        "altitude_agl": 1238.1,
        "rocket_gps_altitude": 1240.1,
        "rocket_latitude": 41.015236,
        "rocket_longitude": 28.979540,
        "payload_gps_altitude": 115.7,
        "payload_latitude": 41.015240,
        "payload_longitude": 28.979535,
        "stage_gps_altitude": 110.2,
        "stage_latitude": 41.015230,
        "stage_longitude": 28.979525,
        "gyro_x": 0.26,
        "gyro_y": -0.11,
        "gyro_z": 0.61,
        "accel_x": -0.09,
        "accel_y": 0.10,
        "accel_z": -0.90,
        "angle": 15.8,
        "status_code": 4
    }
    
    # Generate packets using both methods
    packet_rxbackend = create_tx_packet(test_data)
    packet_txcheck = generate_txcheck_packet(4)
    
    print(f"📦 Packet lengths:")
    print(f"   rxbackend: {len(packet_rxbackend)} bytes")
    print(f"   txCheck:   {len(packet_txcheck)} bytes")
    
    print(f"\n🔍 Header comparison:")
    print(f"   rxbackend: {[f'{b:02X}' for b in packet_rxbackend[:4]]}")
    print(f"   txCheck:   {[f'{b:02X}' for b in packet_txcheck[:4]]}")
    
    print(f"\n🏷️  Team ID and Counter:")
    print(f"   rxbackend: Team={packet_rxbackend[4]}, Counter={packet_rxbackend[5]}")
    print(f"   txCheck:   Team={packet_txcheck[4]}, Counter={packet_txcheck[5]}")
    
    print(f"\n🔢 Checksum comparison:")
    print(f"   rxbackend: {packet_rxbackend[75]:02X}")
    print(f"   txCheck:   {packet_txcheck[75]:02X}")
    
    print(f"\n📄 Footer comparison:")
    print(f"   rxbackend: {[f'{b:02X}' for b in packet_rxbackend[-2:]]}")
    print(f"   txCheck:   {[f'{b:02X}' for b in packet_txcheck[-2:]]}")
    
    # Check if packets are identical
    if packet_rxbackend == packet_txcheck:
        print(f"\n✅ SUCCESS: Packets are identical!")
        return True
    else:
        print(f"\n❌ FAILURE: Packets are different!")
        
        # Find differences
        for i, (b1, b2) in enumerate(zip(packet_rxbackend, packet_txcheck)):
            if b1 != b2:
                print(f"   Difference at byte {i}: rxbackend={b1:02X}, txCheck={b2:02X}")
        
        return False

if __name__ == "__main__":
    success = test_packet_formats()
    sys.exit(0 if success else 1) 