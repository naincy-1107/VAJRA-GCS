
import eventlet
eventlet.monkey_patch()

import threading
import time
import struct
from collections import deque
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO
import serial.tools.list_ports
import serial

# --- Global State & Configuration ---
gcs_state = {
    "latest_telemetry": {"status": "Disconnected"},
    "config": {
        "team_id": 690600,
        "target_altitude": 8000,  # meters
        "category_max_altitude": 10000,  # meters for Reach Coef calculation
        "static_margin": 2.3,  # pre-calculated static margin
        "mission_start_time": None,  # Will be set when first packet is received
    },
    "stats": {
        "packet_loss_percentage": 0,
        "total_packets_received": 0,
        "total_packets_lost": 0,
        "data_rate_hz": 0,
        "packet_rate_hz": 0,
    },
    "history": {
        "packet_timestamps": deque(maxlen=50),
        "altitude_history": deque(maxlen=10),  # for descent speed calculation
        "last_packet_counter": None,
        "last_altitude": 0,
        "last_timestamp": 0,
    },
    "calculated": {
        "deviation_coef": 0,
        "reach_coef": 0,
        "rocket_descent_speed": 0,
        "payload_descent_speed": 0,
        "flight_phase": "Standby",
        "parachute_status": {"primary": "Not Deployed", "secondary": "Not Deployed"},
        "separation_status": "Pending",
        "gps_status": {"rocket": "Unknown", "payload": "Unknown"},
    }
}

data_lock = threading.Lock()
serial_thread = None
stop_thread_event = threading.Event()

# Auto-port detection and configuration
tx_serial = None
rx_serial = None
auto_port_config = {
    "rx_port": None,
    "tx_port": '/dev/ttyACM0',
    "rx_baud": 9600,    # RX port receives XBee data at 9600 baud
    "tx_baud": 19200,   # TX port transmits binary data at 19200 baud
    "connected": False,
    "mode": "SIMPLE",  # SIMPLE, FULL, or COMMAND mode
    "auto_detect": True,
    "detection_interval": 5  # seconds
}

# TX command processing
tx_command_buffer = bytearray()
tx_last_command_time = 0

# --- Flask & SocketIO Setup ---
app = Flask(__name__, static_url_path='/static', static_folder='static')
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ========== Flight Phase Decoding ==========
def decode_flight_phase(status_code):
    """Decode status code to flight phase"""
    phases = {
        0: "Standby",
        1: "Armed",
        2: "Flight/Ascent", 
        3: "Apogee",
        4: "Descent/Recovery",
        5: "Landing"
    }
    return phases.get(status_code, f"Unknown ({status_code})")

def decode_parachute_status(status_code):
    """Decode parachute deployment status from status code (TEKNOFEST RGS: 1–4)"""
    # 1: Armed, 2: Flight, 3: Primary Chute Deployed, 4: Both Chutes Deployed
    if status_code == 1:
        return {"primary": "Not Deployed", "secondary": "Not Deployed"}
    elif status_code == 2:
        return {"primary": "Not Deployed", "secondary": "Not Deployed"}
    elif status_code == 3:
        return {"primary": "Deployed", "secondary": "Not Deployed"}
    elif status_code == 4:
        return {"primary": "Deployed", "secondary": "Deployed"}
    else:
        return {"primary": "Unknown", "secondary": "Unknown"}

def calculate_gps_status(lat, lon, alt):
    """Determine GPS status based on coordinates"""
    if lat != 0 and lon != 0 and alt > 0:
        return "Active"
    return "No Fix"

def calculate_integration_bonus(deviation_coef, reach_coef):
    """Calculate integration bonus points based on performance coefficients"""
    base_bonus = 100
    # Bonus calculation: base + performance bonuses
    deviation_bonus = int(deviation_coef * 50)  # Up to 50 points for accuracy
    reach_bonus = int(reach_coef * 50)          # Up to 50 points for altitude
    total_bonus = base_bonus + deviation_bonus + reach_bonus
    return min(total_bonus, 200)  # Cap at 200 points

# --- TX PORT FUNCTIONS ---
def calculate_checksum_tx(data):
    """Calculate XOR checksum for TX packets"""
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum

def create_tx_packet(telemetry_data):
    """Create TX packet in exact Arduino format (78 bytes)"""
    packet = bytearray()
    
    # Header: FF FF 54 52 (exact Arduino format)
    packet.append(0xFF)
    packet.append(0xFF)
    packet.append(0x54)
    packet.append(0x52)
    
    # Team ID and packet counter
    packet.append(telemetry_data.get("team_id", 690600))
    packet.append(telemetry_data.get("packet_counter", 0))
    
    # 17 float values (68 bytes) - exact Arduino format
    values = [
        telemetry_data.get("altitude_agl", 0.0),                    # 0: altitude_agl
        telemetry_data.get("rocket_gps_altitude", 0.0),             # 1: rocket_gps_altitude
        telemetry_data.get("rocket_latitude", 0.0),                 # 2: rocket_latitude
        telemetry_data.get("rocket_longitude", 0.0),                # 3: rocket_longitude
        telemetry_data.get("payload_gps_altitude", 0.0),            # 4: payload_gps_altitude
        telemetry_data.get("payload_latitude", 0.0),                # 5: payload_latitude
        telemetry_data.get("payload_longitude", 0.0),               # 6: payload_longitude
        telemetry_data.get("stage_gps_altitude", 0.0),              # 7: stage_gps_altitude
        telemetry_data.get("stage_latitude", 0.0),                  # 8: stage_latitude
        telemetry_data.get("stage_longitude", 0.0),                 # 9: stage_longitude
        telemetry_data.get("gyro_x", 0.0),                          # 10: gyro_x
        telemetry_data.get("gyro_y", 0.0),                          # 11: gyro_y
        telemetry_data.get("gyro_z", 0.0),                          # 12: gyro_z
        telemetry_data.get("accel_x", 0.0),                         # 13: accel_x
        telemetry_data.get("accel_y", 0.0),                         # 14: accel_y
        telemetry_data.get("accel_z", 0.0),                         # 15: accel_z
        telemetry_data.get("angle", 0.0)                            # 16: angle
    ]
    
    for value in values:
        packet.extend(struct.pack('<f', value))
    
    # Status code
    packet.append(telemetry_data.get("status_code", 0))
    
    # Checksum (sum of bytes 4-75, mod 256) - exact Arduino format
    checksum = sum(packet[4:75]) % 256
    packet.append(checksum)
    
    # Footer: 0D 0A (exact Arduino format)
    packet.append(0x0D)
    packet.append(0x0A)
    
    return bytes(packet)

def create_simple_tx_packet(telemetry_data):
    """Create TX packet in same format as Arduino (78 bytes)"""
    packet = bytearray()
    
    # Header: FF FF 54 52 (same as Arduino)
    packet.append(0xFF)
    packet.append(0xFF)
    packet.append(0x54)
    packet.append(0x52)
    
    # Team ID and packet counter
    packet.append(telemetry_data.get("team_id", 690600))
    packet.append(telemetry_data.get("packet_counter", 0))
    
    # 17 float values (68 bytes) - same as Arduino format
    values = [
        telemetry_data.get("altitude_agl", 0.0),                    # 0: altitude_agl
        telemetry_data.get("rocket_gps_altitude", 0.0),             # 1: rocket_gps_altitude
        telemetry_data.get("rocket_latitude", 0.0),                 # 2: rocket_latitude
        telemetry_data.get("rocket_longitude", 0.0),                # 3: rocket_longitude
        telemetry_data.get("payload_gps_altitude", 0.0),            # 4: payload_gps_altitude
        telemetry_data.get("payload_latitude", 0.0),                # 5: payload_latitude
        telemetry_data.get("payload_longitude", 0.0),               # 6: payload_longitude
        telemetry_data.get("stage_gps_altitude", 0.0),              # 7: stage_gps_altitude
        telemetry_data.get("stage_latitude", 0.0),                  # 8: stage_latitude
        telemetry_data.get("stage_longitude", 0.0),                 # 9: stage_longitude
        telemetry_data.get("gyro_x", 0.0),                          # 10: gyro_x
        telemetry_data.get("gyro_y", 0.0),                          # 11: gyro_y
        telemetry_data.get("gyro_z", 0.0),                          # 12: gyro_z
        telemetry_data.get("accel_x", 0.0),                         # 13: accel_x
        telemetry_data.get("accel_y", 0.0),                         # 14: accel_y
        telemetry_data.get("accel_z", 0.0),                         # 15: accel_z
        telemetry_data.get("angle", 0.0)                            # 16: angle
    ]
    
    for value in values:
        packet.extend(struct.pack('<f', value))
    
    # Status code
    packet.append(telemetry_data.get("status_code", 0))
    
    # Checksum (sum of bytes 4-75, mod 256) - same as Arduino format
    checksum = sum(packet[4:75]) % 256
    packet.append(checksum)
    
    # Footer: 0D 0A (same as Arduino)
    packet.append(0x0D)
    packet.append(0x0A)
    
    return bytes(packet)

def send_to_tx_port(telemetry_data):
    """Send telemetry data to TX port at 19200 baud using enhanced packet format"""
    global tx_serial, auto_port_config
    
    print(f"[DEBUG] TX send attempt - tx_serial: {tx_serial is not None}, connected: {auto_port_config['connected']}")
    
    if not tx_serial or not auto_port_config["connected"]:
        print(f"[DEBUG] TX send failed - tx_serial: {tx_serial is not None}, connected: {auto_port_config['connected']}")
        return False
        
    try:
        # Use enhanced packet format (from txCheck.py)
        packet = create_enhanced_tx_packet(telemetry_data)
        
        if not packet:
            print("[ERROR] Failed to create TX packet")
            return False
        
        # Send packet at 19200 baud
        tx_serial.write(packet)
        tx_serial.flush()
        
        # Debug output
        packet_hex = ' '.join([f"{b:02X}" for b in packet[:20]])  # Show first 20 bytes
        if len(packet) > 20:
            packet_hex += "..."
        print(f"[TX] Sent {len(packet)}B @ 19200 baud: {packet_hex}")
        print(f"[TX] Alt:{telemetry_data.get('altitude_agl', 0):.1f}m AccZ:{telemetry_data.get('accel_z', 0):.2f}g")
        print(f"[TX] Format: Enhanced Arduino 78-byte packet (FF FF 54 52 header)")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] TX send failed: {e}")
        auto_port_config["connected"] = False
        return False

def send_to_rx_port(command):
    """Send command to RX port"""
    global rx_serial, auto_port_config
    
    if not rx_serial or not auto_port_config.get("rx_port"):
        return False
        
    try:
        # Send command as bytes
        command_bytes = command.encode('utf-8')
        rx_serial.write(command_bytes)
        rx_serial.flush()
        
        print(f"[RX] Sent command: {command.strip()}")
        return True
        
    except Exception as e:
        print(f"[ERROR] RX send failed: {e}")
        return False

# ========== XBee Serial Communication Functions ==========
def listen_xbee_serial(port, callback, stop_event, baud_rate=9600):
    """
    Listen to XBee serial port and parse comma-separated string data.
    Calls callback function with parsed data.
    """
    print(f"[XBEE] Starting XBee serial listener on {port} @ {baud_rate} baud")
    
    try:
        # Check if port exists
        import os
        if not os.path.exists(port):
            print(f"[ERROR] Port {port} does not exist")
            return
            
        # Open the port
        ser = serial.Serial(port, baud_rate, timeout=1, exclusive=True)
        print(f"[XBEE] Connected to {port} @ {baud_rate} baud")
        
        while not stop_event.is_set():
            try:
                if ser.in_waiting > 0:
                    # Read a line of text from the XBee (until a newline character)
                    line = ser.readline().decode('utf-8').strip()
                    
                    if line:
                        print(f"[XBEE] Raw line: {line}")
                        
                        # Parse the XBee string data
                        parsed_data = parse_xbee_string(line)
                        
                        if parsed_data:
                            print(f"[XBEE] Successfully parsed packet {parsed_data.get('packet_counter', 0)} from {port}")
                            callback(parsed_data)
                        else:
                            print(f"[XBEE] Failed to parse data from {port}")
                else:
                    # No data available, small delay to prevent busy waiting
                    time.sleep(0.01)
                            
            except Exception as e:
                print(f"[ERROR] XBee serial read error: {e}")
                print(f"[INFO] Attempting to reconnect in 5 seconds...")
                time.sleep(5)
                break
                
    except Exception as e:
        print(f"[ERROR] Failed to connect to XBee port {port}: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print(f"[XBEE] Closed connection to {port}")

# ========== Serial Communication Functions ==========
def listen_serial(port, callback, stop_event, baud_rate=19200):
    """
    Listen to serial port and parse 78-byte packets.
    Calls callback function with parsed data.
    """
    import struct
    
    print(f"[SERIAL] Starting serial listener on {port} @ {baud_rate} baud")
    
    try:
        # Check if port is already in use
        import os
        if not os.path.exists(port):
            print(f"[ERROR] Port {port} does not exist")
            return
            
        # Try to open the port with exclusive access
        ser = serial.Serial(port, baud_rate, timeout=1, exclusive=True)
        print(f"[SERIAL] Connected to {port}")
        
        packet_buffer = bytearray()
        
        while not stop_event.is_set():
            try:
                if ser.in_waiting > 0:
                    # Read available data
                    data = ser.read(ser.in_waiting)
                    
                    # Check if we actually got data
                    if len(data) == 0:
                        print(f"[WARN] Port reports data available but read returned empty - possible port conflict")
                        time.sleep(0.1)  # Small delay to avoid busy waiting
                        continue
                    
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
                            if packet_buffer[i] == 0xFF and packet_buffer[i + 1] == 0xFF:
                                start_idx = i
                                break
                        
                        if start_idx == -1:
                            # No packet start found, clear buffer
                            packet_buffer.clear()
                            break
                        
                        # Check if we have a complete packet
                        if len(packet_buffer) >= start_idx + 78:
                            packet = packet_buffer[start_idx:start_idx + 78]
                            
                            # Validate packet end (CR LF)
                            if packet[-2] == 0x0D and packet[-1] == 0x0A:
                                # Parse 78-byte packet
                                try:
                                    parsed_data = parse_78byte_packet(packet)
                                    if parsed_data:
                                        print(f"[PARSED] Packet {parsed_data.get('packet_counter', 0)} from {port}")
                                        callback(parsed_data)
                                except Exception as e:
                                    print(f"[ERROR] Failed to parse packet: {e}")
                                
                                # Remove the processed packet from buffer
                                packet_buffer = packet_buffer[start_idx + 78:]
                            else:
                                # Incomplete packet, wait for more data
                                break
                        else:
                            # Incomplete packet, wait for more data
                            break
                else:
                    # No data available, small delay to prevent busy waiting
                    time.sleep(0.01)
                            
            except Exception as e:
                print(f"[ERROR] Serial read error: {e}")
                print(f"[INFO] Attempting to reconnect in 5 seconds...")
                time.sleep(5)
                break
                
    except Exception as e:
        print(f"[ERROR] Failed to connect to {port}: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print(f"[SERIAL] Closed connection to {port}")

def parse_78byte_packet(packet):
    """
    Parse 78-byte telemetry packet according to Arduino format.
    Format: FF FF 54 52 + TeamID + Counter + 17 floats + Status + Checksum + CR LF
    """
    try:
        if len(packet) != 78:
            return None
        
        # Validate header
        if packet[0] != 0xFF or packet[1] != 0xFF or packet[2] != 0x54 or packet[3] != 0x52:
            print(f"[ERROR] Invalid header: {[f'{b:02X}' for b in packet[:4]]}")
            return None
            
        # Parse packet structure
        data = {}
        
        # Raw hex data for frontend display
        data['raw_hex'] = ' '.join([f"{b:02X}" for b in packet])
        
        # Header (4 bytes)
        data['header'] = packet[0:4]
        
        # Team ID (1 byte)
        data['team_id'] = packet[4]
        
        # Packet counter (1 byte)
        data['packet_counter'] = packet[5]
        
        # Parse 17 float values starting from byte 6
        float_idx = 6
        float_names = [
            'altitude_agl',           # 0
            'rocket_gps_altitude',    # 1
            'rocket_latitude',        # 2
            'rocket_longitude',       # 3
            'payload_gps_altitude',   # 4
            'payload_latitude',       # 5
            'payload_longitude',      # 6
            'stage_gps_altitude',     # 7
            'stage_latitude',         # 8
            'stage_longitude',        # 9
            'gyro_x',                 # 10
            'gyro_y',                 # 11
            'gyro_z',                 # 12
            'accel_x',                # 13
            'accel_y',                # 14
            'accel_z',                # 15
            'angle'                   # 16
        ]
        
        for i, name in enumerate(float_names):
            if float_idx + 4 <= len(packet):
                value = struct.unpack('<f', packet[float_idx:float_idx+4])[0]
                data[name] = value
                float_idx += 4
            else:
                print(f"[ERROR] Packet too short for float {name}")
                return None
        
        # Status code (1 byte)
        data['status_code'] = packet[float_idx]
        float_idx += 1
        
        # Checksum (1 byte)
        data['checksum'] = packet[float_idx]
        float_idx += 1
        
        # Footer (2 bytes)
        data['footer'] = packet[float_idx:float_idx+2]
        
        # Validate checksum (sum of bytes 4-74)
        calculated_checksum = 0
        for i in range(4, 75):  # From Team ID to Status
            calculated_checksum += packet[i]
        calculated_checksum = calculated_checksum % 256
        
        if calculated_checksum != data['checksum']:
            print(f"[WARN] Checksum mismatch: calculated={calculated_checksum:02X}, received={data['checksum']:02X}")
            print(f"[DEBUG] Packet data: {[f'{b:02X}' for b in packet[:20]]}...")
            print(f"[INFO] Accepting packet despite checksum mismatch for testing")
        
        return data
        
    except Exception as e:
        print(f"[ERROR] Packet parsing error: {e}")
        return None

# Global variable for checksum errors
checksum_errors = 0

# ========== Calculation & Helper Functions ==========
def update_calculations(telemetry_data):
    """Calculate derived values and augment the telemetry packet."""
    with data_lock:
        current_time = time.time()
        
        # Set mission start time on first packet
        if gcs_state["config"]["mission_start_time"] is None:
            gcs_state["config"]["mission_start_time"] = current_time
        
        # --- Data Rate & Packet Loss Calculation ---
        gcs_state["history"]["packet_timestamps"].append(current_time)
        
        # Calculate data rate (packets per second)
        if len(gcs_state["history"]["packet_timestamps"]) > 1:
            time_diff = gcs_state["history"]["packet_timestamps"][-1] - gcs_state["history"]["packet_timestamps"][0]
            if time_diff > 0:
                gcs_state["stats"]["data_rate_hz"] = round((len(gcs_state["history"]["packet_timestamps"]) - 1) / time_diff, 1)
                gcs_state["stats"]["packet_rate_hz"] = gcs_state["stats"]["data_rate_hz"]

        # --- Packet Loss Calculation ---
        last_counter = gcs_state["history"]["last_packet_counter"]
        current_counter = telemetry_data.get("packet_counter")
        
        if last_counter is not None and current_counter is not None:
            gcs_state["stats"]["total_packets_received"] += 1
            
            # Handle counter rollover (0-255)
            if current_counter > last_counter:
                packets_lost = current_counter - last_counter - 1
            else:
                packets_lost = (255 - last_counter) + current_counter
                
            if 0 <= packets_lost < 50:  # Plausible loss range
                gcs_state["stats"]["total_packets_lost"] += packets_lost
                
            total_expected = gcs_state["stats"]["total_packets_received"] + gcs_state["stats"]["total_packets_lost"]
            if total_expected > 0:
                gcs_state["stats"]["packet_loss_percentage"] = round((gcs_state["stats"]["total_packets_lost"] / total_expected) * 100, 2)
                
        gcs_state["history"]["last_packet_counter"] = current_counter

        # --- Altitude-based Calculations ---
        current_alt = telemetry_data.get("altitude_agl", 0)
        
        # Store altitude history for descent speed
        gcs_state["history"]["altitude_history"].append({
            "altitude": current_alt,
            "timestamp": current_time
        })
        
        # Calculate descent speeds (rocket and payload)
        if len(gcs_state["history"]["altitude_history"]) >= 2:
            recent = gcs_state["history"]["altitude_history"][-1]
            previous = gcs_state["history"]["altitude_history"][-2]
            
            time_delta = recent["timestamp"] - previous["timestamp"]
            if time_delta > 0:
                alt_delta = previous["altitude"] - recent["altitude"]  # Positive when descending
                descent_speed = round(alt_delta / time_delta, 1)
                
                # Only update if descending
                if descent_speed > 0:
                    gcs_state["calculated"]["rocket_descent_speed"] = descent_speed
                    # Assume payload descent speed is similar for now
                    gcs_state["calculated"]["payload_descent_speed"] = descent_speed

        # --- Performance Coefficients ---
        target_alt = gcs_state["config"]["target_altitude"]
        max_alt = gcs_state["config"]["category_max_altitude"]
        
        # Deviation Coefficient: 1 - |Actual - Target| / Target
        if target_alt > 0:
            deviation = abs(current_alt - target_alt) / target_alt
            gcs_state["calculated"]["deviation_coef"] = round(max(0, 1 - deviation), 3)
        
        # Reach Coefficient: Actual / Category Max Altitude
        if max_alt > 0:
            gcs_state["calculated"]["reach_coef"] = round(current_alt / max_alt, 3)

        # --- Flight Status Decoding ---
        status_code = telemetry_data.get("status_code", 0)
        gcs_state["calculated"]["flight_phase"] = decode_flight_phase(status_code)
        gcs_state["calculated"]["parachute_status"] = decode_parachute_status(status_code)
        
        # Separation status (simple logic based on altitude and phase)
        if status_code >= 3 and current_alt > 1000:  # Apogee or descent phase
            gcs_state["calculated"]["separation_status"] = "Confirmed"
        
        # --- GPS Status ---
        gcs_state["calculated"]["gps_status"] = {
            "rocket": calculate_gps_status(
                telemetry_data.get("rocket_latitude", 0),
                telemetry_data.get("rocket_longitude", 0),
                telemetry_data.get("rocket_gps_altitude", 0)
            ),
            "payload": calculate_gps_status(
                telemetry_data.get("payload_latitude", 0),
                telemetry_data.get("payload_longitude", 0),
                telemetry_data.get("payload_gps_altitude", 0)
            )
        }

        # Update latest telemetry
        gcs_state["latest_telemetry"].update(telemetry_data)
        gcs_state["latest_telemetry"]["status"] = "Receiving Data"
        gcs_state["latest_telemetry"]["timestamp"] = current_time

        # Create structured packet for frontend
        structured_packet = {
            # Raw telemetry data (single values from Arduino)
            **telemetry_data,
            
            # Communication status
            "communication": {
                "rx_tx_packets": f"{gcs_state['stats']['total_packets_received']} / {gcs_state['stats']['total_packets_received']}",
                "data_rate_hz": gcs_state["stats"]["data_rate_hz"],
                "packet_rate_hz": gcs_state["stats"]["packet_rate_hz"],
                "packet_loss_percentage": gcs_state["stats"]["packet_loss_percentage"]
            },
            
            # Flight status
            "flight_status": {
                "phase": gcs_state["calculated"]["flight_phase"],
                "parachute_primary": gcs_state["calculated"]["parachute_status"]["primary"],
                "parachute_secondary": gcs_state["calculated"]["parachute_status"]["secondary"],
                "separation": gcs_state["calculated"]["separation_status"]
            },
            
            # Descent speeds
            "descent_speeds": {
                "rocket": gcs_state["calculated"]["rocket_descent_speed"],
                "payload": gcs_state["calculated"]["payload_descent_speed"]
            },
            
            # Locator systems
            "locator_systems": {
                "rocket_gps": gcs_state["calculated"]["gps_status"]["rocket"],
                "payload_gps": gcs_state["calculated"]["gps_status"]["payload"]
            },
            
            # Performance metrics
            "performance": {
                "target_altitude": target_alt,
                "actual_altitude": current_alt,
                "deviation_coef": gcs_state["calculated"]["deviation_coef"],
                "reach_coef": gcs_state["calculated"]["reach_coef"]
            },
            
            # Static margin
            "static_margin": gcs_state["config"]["static_margin"],
            
            # Integration bonus points (calculated based on performance)
            "integration_bonus": calculate_integration_bonus(gcs_state["calculated"]["deviation_coef"], gcs_state["calculated"]["reach_coef"]),
            
            # Mission time
            "mission_time": int(current_time - gcs_state["config"]["mission_start_time"]) if gcs_state["config"]["mission_start_time"] else 0,
            
            # Statistics
            "statistics": {
                "packets_sent": gcs_state["stats"]["total_packets_received"],
                "packet_loss": gcs_state["stats"]["packet_loss_percentage"],
                "checksum_errors": checksum_errors
            }
        }

        return structured_packet
    
def clean_data_for_json(data):
    """Convert bytearray and bytes objects to strings for JSON serialization."""
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned[key] = clean_data_for_json(value)
        return cleaned
    elif isinstance(data, list):
        return [clean_data_for_json(item) for item in data]
    elif isinstance(data, bytearray):
        return data.hex()
    elif isinstance(data, bytes):
        return data.hex()
    else:
        return data
    
def on_packet(data):
    """Callback function for when a new XBee telemetry packet is received."""
    try:
        # Update packet statistics
        with data_lock:
            gcs_state["stats"]["total_packets_received"] += 1
            current_time = time.time()
            gcs_state["history"]["packet_timestamps"].append(current_time)
            
            # Set mission start time if not set
            if not gcs_state["config"]["mission_start_time"]:
                gcs_state["config"]["mission_start_time"] = current_time
        
        print(f"[INFO] Backend received XBee telemetry: Team {data.get('team_id')}, Counter: {data.get('packet_counter')}")
        print(f"[DATA] XBee packet data: {data}")
        
        # Log key telemetry values
        print(f"[TELEMETRY] Altitude: {data.get('altitude_agl', 0):.1f}m")
        print(f"[TELEMETRY] GPS: Lat={data.get('rocket_latitude', 0):.6f}, Lon={data.get('rocket_longitude', 0):.6f}")
        print(f"[TELEMETRY] IMU: AccZ={data.get('accel_z', 0):.2f}g, GyroZ={data.get('gyro_z', 0):.2f}°/s")
        print(f"[TELEMETRY] Angle: {data.get('angle', 0):.1f}°")
        print(f"[TELEMETRY] Status: {data.get('status_code', 0)}")
        
        structured_packet = update_calculations(data)
        
        # Forward to TX port if connected
        if auto_port_config["connected"]:
            if send_to_tx_port(data):
                # Track forwarding statistics
                gcs_state["packets_forwarded"] = gcs_state.get("packets_forwarded", 0) + 1
                gcs_state["last_forwarded_time"] = time.time()
                print(f"[FORWARD] XBee packet forwarded to TX port (Total: {gcs_state['packets_forwarded']})")
            else:
                print(f"[ERROR] Failed to forward XBee packet to TX port")
        else:
            print(f"[WARN] TX port not connected - XBee packet not forwarded")
        
        # Clean data for JSON serialization
        cleaned_packet = clean_data_for_json(structured_packet)
        
        # Broadcast the augmented data to all connected web clients immediately
        print(f"[DEBUG] Emitting XBee telemetry data via Socket.IO...")
        socketio.emit('telemetry', cleaned_packet)
        print(f"[DEBUG] XBee telemetry data emitted successfully")
    except Exception as e:
        print(f"[ERROR] Error processing XBee packet: {e}")
        import traceback
        traceback.print_exc()

def get_usb_serial_ports():
    """Get all available USB serial ports with detailed information"""
    ports = list(serial.tools.list_ports.comports())
    usb_ports = []

    for p in ports:
        if ('USB' in p.description.upper()) or ('USB' in p.hwid.upper()):
            usb_ports.append({
                'device': p.device, 
                'description': p.description,
                'hwid': p.hwid,
                'manufacturer': p.manufacturer,
                'product': p.product,
                'vid': p.vid,
                'pid': p.pid
            })
    return usb_ports

def detect_arduino_ports():
    """Automatically detect Arduino-compatible ports"""
    ports = get_usb_serial_ports()
    arduino_ports = []
    
    for port in ports:
        description = port['description'].upper()
        hwid = port['hwid'].upper()
        
        # Common Arduino identifiers
        arduino_indicators = [
            'ARDUINO', 'CH340', 'CH341', 'CP210', 'FTDI', 'PL2303',
            'USB-SERIAL', 'USB SERIAL', 'USB2.0-SERIAL', 'USB2.0 SERIAL'
        ]
        
        is_arduino = any(indicator in description or indicator in hwid for indicator in arduino_indicators)
        
        if is_arduino:
            arduino_ports.append(port)
    
    return arduino_ports

def auto_connect_ports():
    """Automatically connect to available Arduino ports"""
    global auto_port_config, rx_serial, tx_serial
    
    try:
        arduino_ports = detect_arduino_ports()
        
        if not arduino_ports:
            print("[AUTO] No Arduino ports detected")
            return False
            
        print(f"[AUTO] Found {len(arduino_ports)} Arduino port(s):")
        for port in arduino_ports:
            print(f"  - {port['device']}: {port['description']}")
        
        # Try to connect to the first available port as RX
        for port in arduino_ports:
            try:
                if not auto_port_config["rx_port"]:
                    # Test if port is available for RX
                    test_serial = serial.Serial(
                        port=port['device'],
                        baudrate=auto_port_config["rx_baud"],
                        timeout=1
                    )
                    test_serial.close()
                    
                    auto_port_config["rx_port"] = port['device']
                    print(f"[AUTO] Selected RX port: {port['device']}")
                    break
                    
            except Exception as e:
                print(f"[AUTO] Port {port['device']} not available: {e}")
                continue
        
        # Try to connect to a different port as TX (if available)
        for port in arduino_ports:
            if port['device'] != auto_port_config["rx_port"]:
                try:
                    test_serial = serial.Serial(
                        port=port['device'],
                        baudrate=auto_port_config["tx_baud"],
                        timeout=1
                    )
                    test_serial.close()
                    
                    auto_port_config["tx_port"] = port['device']
                    print(f"[AUTO] Selected TX port: {port['device']}")
                    break
                    
                except Exception as e:
                    print(f"[AUTO] Port {port['device']} not available for TX: {e}")
                    continue
        
        # Ensure RX and TX ports are different
        if auto_port_config["tx_port"] == auto_port_config["rx_port"]:
            print(f"[AUTO] Warning: RX and TX ports are the same ({auto_port_config['rx_port']})")
            print(f"[AUTO] TX forwarding will be disabled to prevent feedback loop")
            auto_port_config["tx_port"] = None
            auto_port_config["connected"] = False
        
        return auto_port_config["rx_port"] is not None
        
    except Exception as e:
        print(f"[AUTO] Auto-connection failed: {e}")
        return False

def monitor_ports():
    """Background thread to monitor port availability and auto-reconnect"""
    global auto_port_config
    
    while True:
        try:
            # Check if current ports are still available
            current_rx = auto_port_config.get("rx_port")
            current_tx = auto_port_config.get("tx_port")
            
            if current_rx or current_tx:
                # Test if ports are still accessible
                ports_still_available = True
                
                if current_rx:
                    try:
                        test_serial = serial.Serial(current_rx, auto_port_config["rx_baud"], timeout=0.1)
                        test_serial.close()
                    except:
                        print(f"[MONITOR] RX port {current_rx} no longer available")
                        ports_still_available = False
                
                if current_tx and current_tx != current_rx:
                    try:
                        test_serial = serial.Serial(current_tx, auto_port_config["tx_baud"], timeout=0.1)
                        test_serial.close()
                    except:
                        print(f"[MONITOR] TX port {current_tx} no longer available")
                        ports_still_available = False
                
                if not ports_still_available:
                    print("[MONITOR] Ports disconnected, attempting auto-reconnection...")
                    auto_port_config["rx_port"] = None
                    auto_port_config["tx_port"] = None
                    auto_port_config["connected"] = False
                    initialize_auto_ports()
            
            # Sleep before next check
            time.sleep(auto_port_config["detection_interval"])
            
        except Exception as e:
            print(f"[MONITOR] Port monitoring error: {e}")
            time.sleep(auto_port_config["detection_interval"])

# ========== AUTO PORT INITIALIZATION ==========
def initialize_auto_ports():
    """Initialize RX and TX ports using auto-detection"""
    global auto_port_config, rx_serial, tx_serial, serial_thread, stop_thread_event
    
    try:
        # Auto-detect and connect to ports
        if not auto_connect_ports():
            print("[AUTO] No suitable ports found for auto-connection")
            return False
        
        # Initialize RX port connection
        if auto_port_config["rx_port"]:
            try:
                # Start RX serial listener thread (using XBee listener for string data)
                if serial_thread and serial_thread.is_alive():
                    stop_thread_event.set()
                    serial_thread.join(timeout=2)
                
                stop_thread_event.clear()
                serial_thread = threading.Thread(
                    target=listen_xbee_serial,  # Use XBee listener for string data
                    args=(auto_port_config["rx_port"], on_packet, stop_thread_event, auto_port_config["rx_baud"]),
                    daemon=True,
                    name=f"XBeeThread-{auto_port_config['rx_port']}"
                )
                serial_thread.start()
                print(f"[AUTO] XBee listener started on {auto_port_config['rx_port']}")
                
            except Exception as e:
                print(f"[AUTO] Failed to start XBee listener: {e}")
                return False
        
        # Initialize TX port connection
        if auto_port_config["tx_port"]:
            try:
                # Close existing TX connection if any
                if tx_serial:
                    tx_serial.close()
                
                # Open new TX connection
                tx_serial = serial.Serial(
                    port=auto_port_config["tx_port"],
                    baudrate=auto_port_config["tx_baud"],
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1
                )
                
                auto_port_config["connected"] = True
                print(f"[AUTO] TX connected to {auto_port_config['tx_port']} @ {auto_port_config['tx_baud']} baud")
                
            except Exception as e:
                print(f"[AUTO] Failed to connect TX port: {e}")
                auto_port_config["connected"] = False
        else:
            # No TX port available, set connected to False
            auto_port_config["connected"] = False
            print("[AUTO] No TX port available - forwarding disabled")
        
        return auto_port_config["rx_port"] is not None
        
    except Exception as e:
        print(f"[AUTO] Auto-initialization failed: {e}")
        return False

def initialize_tx_port():
    """Legacy function - now uses auto-detection"""
    return initialize_auto_ports()

# ========== API Routes ==========
@app.route('/api/data', methods=['GET'])
def get_latest_data():
    """API endpoint to get the latest telemetry data."""
    with data_lock:
        return jsonify(gcs_state["latest_telemetry"])

@app.route('/api/ports', methods=['GET'])
def list_available_ports():
    """List available USB serial ports and auto-detected Arduino ports."""
    try:
        all_ports = get_usb_serial_ports()
        arduino_ports = detect_arduino_ports()
        
        return jsonify({
            'all_ports': all_ports,
            'arduino_ports': arduino_ports,
            'auto_config': auto_port_config
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auto-detect', methods=['POST'])
def auto_detect_ports():
    """Auto-detect and connect to available Arduino ports"""
    try:
        success = initialize_auto_ports()
        if success:
            return jsonify({
                'status': 'success',
                'message': f'Auto-detected and connected to RX: {auto_port_config["rx_port"]}, TX: {auto_port_config["tx_port"]}',
                'config': auto_port_config,
                'arduino_ports': detect_arduino_ports()
            })
        else:
            return jsonify({
                'status': 'warning',
                'message': 'No Arduino ports detected',
                'available_ports': get_usb_serial_ports()
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Endpoint to get or set configuration values like target altitude."""
    try:
        with data_lock:
            if request.method == 'POST':
                if not request.is_json:
                    return jsonify({'error': 'Content-Type must be application/json'}), 400
                    
                new_config = request.json
                # Validate input
                if 'target_altitude' in new_config:
                    if not isinstance(new_config['target_altitude'], (int, float)) or new_config['target_altitude'] <= 0:
                        return jsonify({'error': 'Invalid target_altitude'}), 400
                
                gcs_state["config"].update(new_config)
                print(f"[INFO] Configuration updated: {gcs_state['config']}")
                return jsonify({'status': 'success', 'config': gcs_state['config']})
            else:  # GET request
                return jsonify(gcs_state['config'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/connect', methods=['POST'])
def connect_serial():
    """Connect to specified serial port or use auto-detection."""
    global serial_thread, stop_thread_event
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
        
        # Check if auto-connect is requested
        if request.json.get('auto', False):
            success = initialize_auto_ports()
            if success:
                return jsonify({
                    'status': 'success',
                    'message': f'Auto-connected to RX: {auto_port_config["rx_port"]}, TX: {auto_port_config["tx_port"]}',
                    'config': auto_port_config
                })
            else:
                return jsonify({'error': 'Auto-connection failed - no suitable ports found'}), 500
        
        # Manual connection (legacy support)
        port = request.json.get('port')
        baud = int(request.json.get('baud', 19200))
        if not port or not isinstance(port, str):
            return jsonify({'error': 'Valid port must be specified'}), 400
        if not (port.startswith('/dev/') or port.startswith('COM')):
            return jsonify({'error': 'Invalid port format'}), 400
        
        # Stop existing connection
        if serial_thread and serial_thread.is_alive():
            print('[DEBUG] Stopping previous serial thread...')
            stop_thread_event.set()
            serial_thread.join(timeout=5)  # Increased timeout
            if serial_thread.is_alive():
                print('[WARN] Previous thread did not stop gracefully')
            else:
                print('[DEBUG] Previous serial thread stopped.')
            time.sleep(1)  # Give OS more time to release the port
        
        # Start new connection with selected baud rate
        print(f'[DEBUG] Starting new serial thread for {port} @ {baud}')
        stop_thread_event.clear()
        serial_thread = threading.Thread(
            target=listen_serial,
            args=(port, on_packet, stop_thread_event, baud),
            daemon=True,
            name=f"SerialThread-{port}"
        )
        serial_thread.start()
        
        # Verify thread started successfully
        time.sleep(0.5)
        if not serial_thread.is_alive():
            raise Exception("Serial thread failed to start")
            
        with data_lock:
            gcs_state["latest_telemetry"]["status"] = f"Connected to {port} @ {baud}"
        print(f"[SUCCESS] Connected to {port} @ {baud}")
        return jsonify({'status': 'success', 'message': f'Connected to {port} @ {baud}'})
    except Exception as e:
        print(f"[ERROR] Connection error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/disconnect', methods=['POST'])
def disconnect_serial():
    """Disconnect from serial port."""
    global serial_thread, stop_thread_event
    
    try:
        if serial_thread and serial_thread.is_alive():
            stop_thread_event.set()
            serial_thread.join(timeout=3)
            
        with data_lock:
            gcs_state["latest_telemetry"]["status"] = "Disconnected"
            
        print("[INFO] Disconnected from serial port")
        return jsonify({'status': 'success', 'message': 'Disconnected'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/zero-altitude', methods=['POST'])
def zero_altitude():
    """Send zero altitude command to RX port"""
    try:
        command = "ZERO_ALT\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Zero altitude command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Zero altitude command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Zero altitude command error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/reset-counters', methods=['POST'])
def reset_counters():
    """Send reset counters command to RX port"""
    try:
        command = "RESET_CNT\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Reset counters command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Reset counters command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Reset counters command error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/main-activate', methods=['POST'])
def activate_main_parachute():
    """Send main parachute activation command to RX port"""
    try:
        command = "MAIN_ACTIVATE\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Main parachute activation command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Main parachute activation command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Main parachute activation command error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/main-release', methods=['POST'])
def release_main_parachute():
    """Send main parachute release command to RX port"""
    try:
        command = "MAIN_RELEASE\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Main parachute release command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Main parachute release command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Main parachute release command error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/backup-activate', methods=['POST'])
def activate_backup_parachute():
    """Send backup parachute activation command to RX port"""
    try:
        command = "BACKUP_ACTIVATE\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Backup parachute activation command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Backup parachute activation command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Backup parachute activation command error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/backup-release', methods=['POST'])
def release_backup_parachute():
    """Send backup parachute release command to RX port"""
    try:
        command = "BACKUP_RELEASE\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Backup parachute release command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Backup parachute release command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Backup parachute release command error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/parachute-status', methods=['POST'])
def parachute_status_check():
    """Send parachute status check command to RX port"""
    try:
        command = "CHUTE_STATUS\n"
        if send_to_rx_port(command):
            print(f"[CONTROL] Parachute status check command sent to RX port")
            return jsonify({'status': 'success', 'message': 'Parachute status check command sent'})
        else:
            return jsonify({'error': 'Failed to send command - RX port not connected'}), 500
    except Exception as e:
        print(f"[ERROR] Parachute status command error: {e}")
        return jsonify({'error': str(e)}), 500



@app.route('/api/tx/connect', methods=['POST'])
def connect_tx_port():
    """Connect to TX port for forwarding telemetry using auto-detection"""
    success = initialize_auto_ports()
    if success:
        return jsonify({
            'status': 'success', 
            'message': f'Auto-connected to RX: {auto_port_config["rx_port"]}, TX: {auto_port_config["tx_port"]}',
            'config': auto_port_config
        })
    else:
        return jsonify({'error': 'Failed to auto-connect to ports'}), 500

@app.route('/api/tx/disconnect', methods=['POST'])
def disconnect_tx_port():
    """Disconnect from TX port"""
    global tx_serial, auto_port_config, serial_thread, stop_thread_event
    
    try:
        # Stop RX listener thread
        if serial_thread and serial_thread.is_alive():
            stop_thread_event.set()
            serial_thread.join(timeout=2)
            serial_thread = None
        
        # Close TX connection
        if tx_serial:
            tx_serial.close()
            tx_serial = None
            
        auto_port_config["connected"] = False
        auto_port_config["rx_port"] = None
        auto_port_config["tx_port"] = None
        
        print("[AUTO] Disconnected from all ports")
        return jsonify({'status': 'success', 'message': 'All ports disconnected'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tx/status', methods=['GET'])
def tx_port_status():
    """Get auto-port status"""
    return jsonify(auto_port_config)

@app.route('/api/ports/status', methods=['GET'])
def get_ports_status():
    """Get status of both RX and TX ports"""
    global serial_thread, stop_thread_event
    
    # Get RX port status
    rx_status = {
        "connected": serial_thread and serial_thread.is_alive(),
        "port": auto_port_config.get("rx_port", "Unknown"),
        "baud": auto_port_config["rx_baud"]
    }
    
    # Get TX port status
    tx_status = {
        "connected": auto_port_config["connected"],
        "port": auto_port_config.get("tx_port", "Unknown"),
        "baud": auto_port_config["tx_baud"],
        "mode": auto_port_config["mode"]
    }
    
    return jsonify({
        "rx": rx_status,
        "tx": tx_status,
        "auto_config": auto_port_config,
        "forwarding": {
            "enabled": rx_status["connected"] and tx_status["connected"],
            "packets_forwarded": gcs_state.get("packets_forwarded", 0),
            "last_forwarded": gcs_state.get("last_forwarded_time", None)
        }
    })

@app.route('/api/tx/mode', methods=['POST'])
def set_tx_mode():
    """Set TX port mode (SIMPLE, FULL, or COMMAND)"""
    try:
        data = request.get_json()
        mode = data.get('mode', 'SIMPLE')
        
        if mode not in ['SIMPLE', 'FULL', 'COMMAND']:
            return jsonify({'error': 'Invalid mode. Use SIMPLE, FULL, or COMMAND'}), 400
            
        auto_port_config["mode"] = mode
        print(f"[AUTO] Mode set to {mode}")
        
        return jsonify({
            'status': 'success', 
            'message': f'TX mode set to {mode}',
            'config': auto_port_config
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/tx-status', methods=['GET'])
def debug_tx_status():
    """Debug endpoint to check TX port status"""
    global tx_serial, auto_port_config
    
    status = {
        "tx_serial_exists": tx_serial is not None,
        "auto_port_config": auto_port_config.copy(),
        "tx_port_available": auto_port_config.get("tx_port") is not None,
        "connected_flag": auto_port_config.get("connected", False)
    }
    
    if tx_serial:
        try:
            status["tx_serial_port"] = tx_serial.port
            status["tx_serial_open"] = tx_serial.is_open
        except Exception as e:
            status["tx_serial_error"] = str(e)
    
    return jsonify(status)

# ========== SocketIO Events ==========
@socketio.on('connect')
def handle_connect():
    print('[INFO] Web client connected via Socket.IO')
    print(f'[DEBUG] Client connected from: {request.environ.get("HTTP_ORIGIN", "Unknown origin")}')
    # Send current state to newly connected client
    with data_lock:
        if gcs_state["latest_telemetry"] and gcs_state["latest_telemetry"].get("status") != "Disconnected":
            print('[DEBUG] Sending current telemetry state to new client')
            # Clean the data before sending to avoid JSON serialization errors
            cleaned_data = clean_data_for_json(gcs_state["latest_telemetry"])
            socketio.emit('telemetry', cleaned_data)
        else:
            print('[DEBUG] No telemetry data to send to new client')

@socketio.on('disconnect')
def handle_disconnect():
    print('[INFO] Web client disconnected from Socket.IO')

@socketio.on('telemetry_request')
def handle_telemetry_request():
    """Handle requests for current telemetry data from frontend"""
    client_id = request.sid
    print(f'📡 Frontend requested telemetry data - Client ID: {client_id}')
    
    with data_lock:
        if gcs_state["latest_telemetry"] and gcs_state["latest_telemetry"].get("status") != "Disconnected":
            print(f'✅ Sending current telemetry data to client {client_id}')
            # Clean the data before sending to avoid JSON serialization errors
            cleaned_data = clean_data_for_json(gcs_state["latest_telemetry"])
            socketio.emit('telemetry', cleaned_data, room=client_id)
        else:
            print(f'⚠️ No telemetry data available to send to client {client_id}')
            # Don't send any data - let frontend show "No Data"

# ========== XBee String Parsing Functions (from xbeeB.py) ==========
def parse_xbee_string(data_string: str):
    """
    Parses the incoming comma-separated string from the XBee.
    Format: altitude,gnssAltitude,latitude,longitude,0,0,0,0,0,0,gyro_x,gyro_y,gyro_z,acc_x,acc_y,acc_z,angle_x
    """
    print(f"[RX] Received XBee String: \"{data_string}\"")
    
    # Split the string by commas
    parts = data_string.strip().split(',')
    
    # Expected format: 17 comma-separated values
    if len(parts) != 17:
        print(f"[ERROR] Invalid XBee string format. Expected 17 comma-separated values, but got {len(parts)}.")
        return None

    try:
        # A helper function to safely convert parts to float, defaulting to 0.0
        def to_float(value_str):
            try:
                return float(value_str) if value_str and value_str.strip() else 0.0
            except ValueError:
                return 0.0

        # A helper function to safely convert parts to int, defaulting to 0
        def to_int(value_str):
            try:
                return int(value_str) if value_str and value_str.strip() else 0
            except ValueError:
                return 0

        # Map the string parts to a dictionary matching the RGS packet structure
        # Format: altitude,gnssAltitude,latitude,longitude,0,0,0,0,0,0,gyro_x,gyro_y,gyro_z,acc_x,acc_y,acc_z,angle_x
        telemetry_data = {
            'team_id': 690600,  # Fixed team ID
            'packet_counter': gcs_state.get("stats", {}).get("total_packets_received", 0) + 1,  # Auto-increment
            'altitude_agl': to_float(parts[0]),                    # altitude
            'rocket_gps_altitude': to_float(parts[1]),             # gnssAltitude
            'rocket_latitude': to_float(parts[2]),                 # latitude
            'rocket_longitude': to_float(parts[3]),                # longitude
            'payload_gps_altitude': to_float(parts[4]),            # 0 (placeholder)
            'payload_latitude': to_float(parts[5]),                # 0 (placeholder)
            'payload_longitude': to_float(parts[6]),               # 0 (placeholder)
            'stage_gps_altitude': to_float(parts[7]),              # 0 (placeholder)
            'stage_latitude': to_float(parts[8]),                  # 0 (placeholder)
            'stage_longitude': to_float(parts[9]),                 # 0 (placeholder)
            'gyro_x': to_float(parts[10]),                         # gyro_x
            'gyro_y': to_float(parts[11]),                         # gyro_y
            'gyro_z': to_float(parts[12]),                         # gyro_z
            'accel_x': to_float(parts[13]),                        # acc_x
            'accel_y': to_float(parts[14]),                        # acc_y
            'accel_z': to_float(parts[15]),                        # acc_z
            'angle': to_float(parts[16]),                          # angle_x
            'status_code': 4  # Default status code for descent/recovery
        }
        
        print(f"[XBEE] Parsed data: Alt={telemetry_data['altitude_agl']:.1f}m, Lat={telemetry_data['rocket_latitude']:.6f}, Lon={telemetry_data['rocket_longitude']:.6f}")
        return telemetry_data
        
    except (ValueError, IndexError) as e:
        print(f"[ERROR] Could not parse XBee string packet. Check data types. Error: {e}")
        return None

# ========== Enhanced TX Packet Creation (from txCheck.py) ==========
def create_enhanced_tx_packet(telemetry_data):
    """Create TX packet in exact Arduino format (78 bytes) - Enhanced version from txCheck.py"""
    packet = bytearray()

    # Header: FF FF 54 52 (exact Arduino format from txCheck.py)
    packet.extend([0xFF, 0xFF, 0x54, 0x52])

    # Team ID and packet counter
    packet.append(telemetry_data.get("team_id", 690600) & 0xFF)
    packet.append(telemetry_data.get("packet_counter", 0) & 0xFF)

    # 17 float values (68 bytes) - exact Arduino format
    float_fields = [
        telemetry_data.get("altitude_agl", 0.0),                    # 0: altitude_agl
        telemetry_data.get("rocket_gps_altitude", 0.0),             # 1: rocket_gps_altitude
        telemetry_data.get("rocket_latitude", 0.0),                 # 2: rocket_latitude
        telemetry_data.get("rocket_longitude", 0.0),                # 3: rocket_longitude
        telemetry_data.get("payload_gps_altitude", 0.0),            # 4: payload_gps_altitude
        telemetry_data.get("payload_latitude", 0.0),                # 5: payload_latitude
        telemetry_data.get("payload_longitude", 0.0),               # 6: payload_longitude
        telemetry_data.get("stage_gps_altitude", 0.0),              # 7: stage_gps_altitude
        telemetry_data.get("stage_latitude", 0.0),                  # 8: stage_latitude
        telemetry_data.get("stage_longitude", 0.0),                 # 9: stage_longitude
        telemetry_data.get("gyro_x", 0.0),                          # 10: gyro_x
        telemetry_data.get("gyro_y", 0.0),                          # 11: gyro_y
        telemetry_data.get("gyro_z", 0.0),                          # 12: gyro_z
        telemetry_data.get("accel_x", 0.0),                         # 13: accel_x
        telemetry_data.get("accel_y", 0.0),                         # 14: accel_y
        telemetry_data.get("accel_z", 0.0),                         # 15: accel_z
        telemetry_data.get("angle", 0.0)                            # 16: angle
    ]

    # Convert float values to bytes using struct.pack
    for value in float_fields:
        packet.extend(struct.pack('<f', value))

    # Status code
    packet.append(telemetry_data.get("status_code", 0) & 0xFF)

    # Checksum (sum of bytes 4-75, mod 256) - exact Arduino format
    checksum = sum(packet[4:75]) % 256
    packet.append(checksum)

    # Footer: 0D 0A (exact Arduino format)
    packet.extend([0x0D, 0x0A])

    # Ensure packet is exactly 78 bytes
    while len(packet) < 78:
        packet.append(0x00)

    return bytes(packet)

# ========== Main Execution ==========
if __name__ == '__main__':
    print("🚀 Starting TEKNOFEST GCS Backend on http://127.0.0.1:5000")
    print("📡 Auto-port detection enabled for RX→TX telemetry forwarding at 19200 baud")
    print("📦 TX Modes: SIMPLE(36B), FULL(78B), COMMAND(Response)")
    print("   SIMPLE: Header(0xAB) + 8×Float(32B) + Checksum + Footer")
    print("   FULL: FF FF + TeamID + Counter + Full telemetry data")
    print("   COMMAND: Command/Response protocol with acknowledgments")
    print()
    print("🔌 Available endpoints:")
    print("   AUTO PORT DETECTION:")
    print("   - POST /api/auto-detect - Auto-detect and connect to Arduino ports")
    print("   - GET  /api/ports - List all USB ports and detected Arduino ports")
    print("   - POST /api/connect - Connect with auto-detection or manual port")
    print("   - POST /api/disconnect - Disconnect from all ports")
    print("   PORT MANAGEMENT:")
    print("   - GET  /api/ports/status - Get status of RX and TX ports")
    print("   - POST /api/tx/mode - Set TX mode (SIMPLE/FULL/COMMAND)")
    print("   TESTING:")
    
    print("   - WebSocket: Socket.IO for real-time data")
    print()
    print("🔄 Data Flow: Arduino → Auto-RX Port → Backend → Auto-TX Port → TX Device")
    print("   All incoming telemetry is automatically forwarded to TX port")
    print("   🔍 Auto-detection supports: Arduino, CH340, CH341, CP210, FTDI, PL2303")
    
    # Initialize auto-port detection and connection
    print("[INIT] Starting auto-port detection...")
    if initialize_auto_ports():
        print(f"[SUCCESS] Auto-port initialization successful")
        print(f"[AUTO] RX Port: {auto_port_config['rx_port']}")
        print(f"[AUTO] TX Port: {auto_port_config['tx_port']}")
    else:
        print(f"[WARNING] Auto-port initialization failed - will retry when ports become available")
    
    # Start port monitoring thread
    monitor_thread = threading.Thread(target=monitor_ports, daemon=True, name="PortMonitor")
    monitor_thread.start()
    print("[INIT] Port monitoring thread started")
    
    socketio.run(app, host='127.0.0.1', port=5000, debug=False, allow_unsafe_werkzeug=True)