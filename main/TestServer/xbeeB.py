import time
import struct
import serial
import serial.tools.list_ports
import threading

# --- Configuration ---
# TODO: Set your actual COM ports here.
# Use device manager on Windows or `ls /dev/tty.*` on macOS/Linux to find them.
XBEE_RX_PORT = "COM3"  # The port receiving string data from your XBee
RGS_TX_PORT = "COM4"   # The port connected to the Referee Ground Station
BAUD_RATE = 19200      # Baud rate for both ports
TEAM_ID = 690600       # Your assigned Team ID

# Global variables for serial connections
rx_serial = None
tx_serial = None
stop_thread = False

def parse_xbee_string(data_string: str):
    """
    Parses the incoming comma-separated string from the XBee.
    The string format is expected to match the RGS packet fields in order.
    Handles '0' or empty values by defaulting to 0.0 for floats and 0 for ints.
    """
    print(f"[RX] Received String: \"{data_string}\"")
    
    # Split the string by commas
    parts = data_string.strip().split(',')
    
    # The RGS packet has 19 distinct data fields after the header (TeamID, Counter, 17 floats, Status)
    if len(parts) != 19:
        print(f"[ERROR] Invalid string format. Expected 19 comma-separated values, but got {len(parts)}.")
        return None

    try:
        # A helper function to safely convert parts to float, defaulting to 0.0
        def to_float(value_str):
            return float(value_str) if value_str else 0.0

        # A helper function to safely convert parts to int, defaulting to 0
        def to_int(value_str):
            return int(value_str) if value_str else 0

        # Map the string parts to a dictionary matching the RGS packet structure
        telemetry_data = {
            'team_id': to_int(parts[0]),
            'packet_counter': to_int(parts[1]),
            'altitude_agl': to_float(parts[2]),
            'rocket_gps_altitude': to_float(parts[3]),
            'rocket_latitude': to_float(parts[4]),
            'rocket_longitude': to_float(parts[5]),
            'payload_gps_altitude': to_float(parts[6]),
            'payload_latitude': to_float(parts[7]),
            'payload_longitude': to_float(parts[8]),
            'stage_gps_altitude': to_float(parts[9]),
            'stage_latitude': to_float(parts[10]),
            'stage_longitude': to_float(parts[11]),
            'gyro_x': to_float(parts[12]),
            'gyro_y': to_float(parts[13]),
            'gyro_z': to_float(parts[14]),
            'accel_x': to_float(parts[15]),
            'accel_y': to_float(parts[16]),
            'accel_z': to_float(parts[17]),
            'angle': to_float(parts[18]),
            'status_code': to_int(parts[19])
        }
        return telemetry_data
    except (ValueError, IndexError) as e:
        print(f"[ERROR] Could not parse string packet. Check data types. Error: {e}")
        return None

def create_rgs_packet(telemetry_data: dict):
    """
    Creates the precise 78-byte binary packet required by the RGS.
    """
    if not telemetry_data:
        return None
        
    packet = bytearray()

    # 1. Header (4 bytes)
    packet.extend([0xFF, 0x54, 0xFF, 0x52])

    # 2. Team ID (1 byte)
    packet.append(telemetry_data.get('team_id', TEAM_ID) & 0xFF)

    # 3. Packet Counter (1 byte)
    packet.append(telemetry_data.get('packet_counter', 0) & 0xFF)

    # 4. Telemetry Values (17 floats = 68 bytes)
    float_fields = [
        'altitude_agl', 'rocket_gps_altitude', 'rocket_latitude', 'rocket_longitude',
        'payload_gps_altitude', 'payload_latitude', 'payload_longitude',
        'stage_gps_altitude', 'stage_latitude', 'stage_longitude',
        'gyro_x', 'gyro_y', 'gyro_z',
        'accel_x', 'accel_y', 'accel_z', 'angle'
    ]
    for field in float_fields:
        # struct.pack '<f' packs the float as a 4-byte little-endian value
        packet.extend(struct.pack('<f', telemetry_data.get(field, 0.0)))

    # 5. Status Code (1 byte)
    packet.append(telemetry_data.get('status_code', 0) & 0xFF)

    # 6. CRC Checksum (1 byte)
    # The checksum is the sum of bytes from index 4 to 74 (inclusive), modulo 256
    checksum = sum(packet[4:75]) % 256
    packet.append(checksum)

    # 7. Footer (2 bytes)
    packet.extend([0x0D, 0x0A])

    return bytes(packet)

def serial_listener_thread():
    """
    A thread that continuously listens to the RX port for incoming string data.
    """
    global rx_serial, tx_serial, stop_thread
    
    while not stop_thread:
        if rx_serial and rx_serial.is_open:
            try:
                # Read a line of text from the XBee (until a newline character)
                if rx_serial.in_waiting > 0:
                    line = rx_serial.readline().decode('utf-8').strip()
                    
                    if line:
                        # Step 1: Parse the incoming string into a dictionary
                        parsed_data = parse_xbee_string(line)
                        
                        if parsed_data:
                            # Step 2: Create the binary RGS packet from the parsed data
                            binary_packet = create_rgs_packet(parsed_data)
                            
                            # Step 3: Send the binary packet to the TX port
                            if tx_serial and tx_serial.is_open and binary_packet:
                                tx_serial.write(binary_packet)
                                packet_hex = ' '.join(f'{b:02X}' for b in binary_packet[:10])
                                print(f"[TX] Sent {len(binary_packet)} bytes to RGS: {packet_hex}...")
                            else:
                                print("[WARN] RGS TX port not available. Cannot forward packet.")
            except Exception as e:
                print(f"[ERROR] An error occurred in the listener thread: {e}")
                time.sleep(1) # Avoid rapid error loops
        else:
            print("[INFO] RX port not connected. Waiting...")
            time.sleep(2)

def main():
    """
    Main function to initialize serial ports and start the listener thread.
    """
    global rx_serial, tx_serial, stop_thread
    
    print("--- GCS String-to-Byte Bridge ---")
    print(f"Listening for strings on: {XBEE_RX_PORT}")
    print(f"Forwarding binary packets to: {RGS_TX_PORT}")
    print(f"Baud Rate: {BAUD_RATE}")
    print("---------------------------------")

    try:
        # Initialize RX Port (from XBee)
        try:
            rx_serial = serial.Serial(XBEE_RX_PORT, BAUD_RATE, timeout=1)
            print(f"[OK] Successfully connected to RX port {XBEE_RX_PORT}.")
        except serial.SerialException as e:
            print(f"[FATAL] Could not open RX port {XBEE_RX_PORT}: {e}")
            return

        # Initialize TX Port (to RGS)
        try:
            tx_serial = serial.Serial(RGS_TX_PORT, BAUD_RATE, timeout=1)
            print(f"[OK] Successfully connected to TX port {RGS_TX_PORT}.")
        except serial.SerialException as e:
            print(f"[FATAL] Could not open TX port {RGS_TX_PORT}: {e}")
            rx_serial.close() # Clean up the other port
            return

        # Start the listener thread
        listener = threading.Thread(target=serial_listener_thread, daemon=True)
        listener.start()
        print("[INFO] Listener thread started. Waiting for data...")

        # Keep the main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down...")
        stop_thread = True
        if rx_serial and rx_serial.is_open:
            rx_serial.close()
        if tx_serial and tx_serial.is_open:
            tx_serial.close()
        print("[INFO] Ports closed. Goodbye.")

if __name__ == '__main__':
    main()