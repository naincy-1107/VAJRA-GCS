#!/usr/bin/env python3
"""
Test script to verify XBee compatibility with 0 values
"""

import struct
import sys

def create_xbee_packet(counter):
    """Create a 78-byte packet with all 0 values for XBee compatibility"""
    packet = bytearray()
    
    # Header: FF FF 54 52
    packet.extend([0xFF, 0xFF, 0x54, 0x52])
    
    # Team ID and packet counter
    packet.append(142)  # Team ID
    packet.append(counter % 256)
    
    # 17 float values (68 bytes) - all set to 0 for XBee
    float_values = [
        0.0,  # altitude_agl
        0.0,  # rocket_gps_altitude
        0.0,  # rocket_latitude
        0.0,  # rocket_longitude
        0.0,  # payload_gps_altitude
        0.0,  # payload_latitude
        0.0,  # payload_longitude
        0.0,  # stage_gps_altitude
        0.0,  # stage_latitude
        0.0,  # stage_longitude
        0.0,  # gyro_x
        0.0,  # gyro_y
        0.0,  # gyro_z
        0.0,  # accel_x
        0.0,  # accel_y
        0.0,  # accel_z
        0.0   # angle
    ]
    
    for value in float_values:
        packet.extend(struct.pack('<f', value))
    
    # Status code (0 for XBee)
    packet.append(0)
    
    # Calculate checksum (sum of bytes 4-75, mod 256)
    checksum = sum(packet[4:75]) % 256
    packet.append(checksum)
    
    # Footer: 0D 0A
    packet.extend([0x0D, 0x0A])
    
    return packet

def test_xbee_packet():
    """Test XBee packet format"""
    print("🧪 Testing XBee Packet Format")
    print("=" * 40)
    
    packet = create_xbee_packet(1)
    
    print(f"📦 Packet length: {len(packet)} bytes")
    print(f"🔍 Header: {[f'{b:02X}' for b in packet[:4]]}")
    print(f"🏷️  Team ID: {packet[4]}")
    print(f"🔢 Counter: {packet[5]}")
    print(f"📊 Status: {packet[74]}")
    print(f"🔢 Checksum: {packet[75]:02X}")
    print(f"📄 Footer: {[f'{b:02X}' for b in packet[-2:]]}")
    
    # Verify all float values are 0
    float_start = 6
    float_count = 17
    all_zeros = True
    
    for i in range(float_count):
        offset = float_start + (i * 4)
        if offset + 4 <= len(packet):
            value = struct.unpack('<f', packet[offset:offset+4])[0]
            if value != 0.0:
                all_zeros = False
                print(f"❌ Float {i}: {value} (should be 0)")
    
    if all_zeros:
        print("✅ All float values are 0 (XBee compatible)")
    else:
        print("❌ Some float values are not 0")
    
    # Verify checksum
    calculated_checksum = sum(packet[4:75]) % 256
    if calculated_checksum == packet[75]:
        print("✅ Checksum is correct")
    else:
        print(f"❌ Checksum mismatch: calculated={calculated_checksum:02X}, stored={packet[75]:02X}")
    
    print(f"\n🎯 XBee compatibility test completed!")
    return all_zeros and calculated_checksum == packet[75]

if __name__ == "__main__":
    success = test_xbee_packet()
    sys.exit(0 if success else 1) 