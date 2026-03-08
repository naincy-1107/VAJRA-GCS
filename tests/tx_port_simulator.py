#!/usr/bin/env python3
"""
TX Port Simulator
Simulates a device receiving data from the TX port to verify data forwarding.
"""

import serial
import struct
import time
import sys

def parse_78byte_packet(packet):
    """Parse 78-byte Arduino packet format"""
    try:
        if len(packet) != 78:
            return None
            
        # Parse packet structure
        data = {}
        
        # Header (4 bytes)
        data['header'] = packet[0:4]
        
        # Team ID (1 byte)
        data['team_id'] = packet[4]
        
        # Packet counter (1 byte)
        data['packet_counter'] = packet[5]
        
        # 17 float values (68 bytes)
        offset = 6
        field_names = [
            'altitude_agl', 'rocket_gps_altitude', 'rocket_latitude', 'rocket_longitude',
            'payload_gps_altitude', 'payload_latitude', 'payload_longitude',
            'stage_gps_altitude', 'stage_latitude', 'stage_longitude',
            'gyro_x', 'gyro_y', 'gyro_z', 'accel_x', 'accel_y', 'accel_z', 'angle'
        ]
        
        for i, name in enumerate(field_names):
            value = struct.unpack('<f', packet[offset:offset+4])[0]
            data[name] = value
            offset += 4
        
        # Status code (1 byte)
        data['status_code'] = packet[74]
        
        # Checksum (1 byte)
        data['checksum'] = packet[75]
        
        # Footer (2 bytes)
        data['footer'] = packet[76:78]
        
        return data
        
    except Exception as e:
        print(f"Error parsing packet: {e}")
        return None

def simulate_tx_receiver(port, duration=10):
    """Simulate a device receiving data from TX port"""
    print(f"📡 TX Port Receiver Simulator")
    print(f"🎯 Listening on: {port}")
    print(f"⏱️  Duration: {duration} seconds")
    print("=" * 50)
    
    try:
        # Connect to serial port
        ser = serial.Serial(port, 19200, timeout=1)
        print(f"✅ Connected to {port} @ 19200 baud")
        
        packet_buffer = bytearray()
        packet_count = 0
        start_time = time.time()
        
        while time.time() - start_time < duration:
            if ser.in_waiting > 0:
                # Read available data
                data = ser.read(ser.in_waiting)
                packet_buffer.extend(data)
                
                # Log raw data
                if len(data) > 0:
                    hex_data = ' '.join([f"{b:02X}" for b in data[:20]])
                    if len(data) > 20:
                        hex_data += "..."
                    print(f"[RAW] {port}: {len(data)} bytes - {hex_data}")
                
                # Process complete 78-byte packets
                while len(packet_buffer) >= 78:
                    # Look for packet start (FF FF)
                    start_idx = -1
                    for i in range(len(packet_buffer) - 1):
                        if packet_buffer[i] == 0xFF and packet_buffer[i+1] == 0xFF:
                            start_idx = i
                            break
                    
                    if start_idx >= 0 and len(packet_buffer) >= start_idx + 78:
                        # Extract complete packet
                        packet = packet_buffer[start_idx:start_idx+78]
                        packet_buffer = packet_buffer[start_idx+78:]
                        
                        # Parse packet
                        parsed_data = parse_78byte_packet(packet)
                        if parsed_data:
                            packet_count += 1
                            print(f"📦 Packet {packet_count}:")
                            print(f"   Team ID: {parsed_data['team_id']}")
                            print(f"   Counter: {parsed_data['packet_counter']}")
                            print(f"   Altitude: {parsed_data['altitude_agl']:.1f}m")
                            print(f"   GPS: Lat={parsed_data['rocket_latitude']:.6f}, Lon={parsed_data['rocket_longitude']:.6f}")
                            print(f"   IMU: AccZ={parsed_data['accel_z']:.2f}g, GyroZ={parsed_data['gyro_z']:.2f}°/s")
                            print(f"   Angle: {parsed_data['angle']:.1f}°")
                            print(f"   Status: {parsed_data['status_code']}")
                            print(f"   Checksum: 0x{parsed_data['checksum']:02X}")
                            print()
                        else:
                            print(f"❌ Failed to parse packet")
                    else:
                        # Not enough data for complete packet
                        break
            else:
                time.sleep(0.01)  # Small delay to prevent busy waiting
        
        # Summary
        elapsed_time = time.time() - start_time
        print(f"📊 Summary:")
        print(f"   Received: {packet_count} packets")
        print(f"   Duration: {elapsed_time:.1f} seconds")
        if elapsed_time > 0:
            print(f"   Rate: {packet_count/elapsed_time:.1f} packets/second")
        
        ser.close()
        print(f"✅ TX receiver simulation completed")
        
    except Exception as e:
        print(f"❌ Error: {e}")

def list_available_ports():
    """List available serial ports"""
    import serial.tools.list_ports
    
    ports = serial.tools.list_ports.comports()
    print("🔍 Available serial ports:")
    for port in ports:
        print(f"   {port.device}: {port.description}")
        if port.hwid:
            print(f"      Hardware ID: {port.hwid}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 tx_port_simulator.py <port> [duration]")
        print("Example: python3 tx_port_simulator.py /dev/ttyACM1 10")
        list_available_ports()
        sys.exit(1)
    
    port = sys.argv[1]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    simulate_tx_receiver(port, duration) 