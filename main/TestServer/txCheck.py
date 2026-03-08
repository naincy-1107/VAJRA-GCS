import serial
import struct
import random
import time

# --- Configuration ---
SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE = 19200
TEAM_ID = 42  # Replace with your official team ID (0-255)

# --- Packet Constants ---
PACKET_LENGTH = 78
HEADER = [0xFF, 0xFF, 0x54, 0x52]
FOOTER = [0x0D, 0x0A]

def float_to_bytes(value):
    """Convert float to 4-byte little endian format."""
    return struct.pack('<f', value)

def calculate_checksum(packet_bytes):
    """Checksum = sum of bytes from Byte 5 to Byte 75, mod 256"""
    return sum(packet_bytes[4:75]) % 256

def generate_random_packet(counter):
    """Generate a valid 78-byte packet."""
    packet = bytearray()

    # Header
    packet += bytearray(HEADER)

    # Byte 5: Team ID
    packet.append(TEAM_ID)

    # Byte 6: Packet counter (0-255)
    packet.append(counter % 256)

    # Remaining data fields (18 float32 values, 1 uint8, checksum, footer)
    float_fields = [
        # Altitude + GPS (rocket, payload, stage)
        random.uniform(0, 5000), random.uniform(0, 5000),
        random.uniform(-90, 90), random.uniform(-180, 180),
        random.uniform(0, 5000), random.uniform(-90, 90), random.uniform(-180, 180),
        random.uniform(0, 5000), random.uniform(-90, 90), random.uniform(-180, 180),
        # Gyroscope X/Y/Z
        random.uniform(-500, 500), random.uniform(-500, 500), random.uniform(-500, 500),
        # Acceleration X/Y/Z
        random.uniform(-16, 16), random.uniform(-16, 16), random.uniform(-16, 16),
        # Angle (0-180)
        random.uniform(0, 180)
    ]

    # Convert float values to bytes
    for f in float_fields:
        packet += float_to_bytes(f)

    # Byte 74: Status (1-4)
    status = random.choice([1, 2, 3, 4])
    packet.append(status)

    # Byte 75: Checksum
    checksum = calculate_checksum(packet)
    packet.append(checksum)

    # Footer: Byte 76, 77
    packet += bytearray(FOOTER)

    # Pad to 78 bytes if needed
    while len(packet) < PACKET_LENGTH:
        packet.append(0x00)

    return packet

def main():
    counter = 0
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            print(f"Sending packets to {SERIAL_PORT} at {BAUD_RATE} baud.")
            while True:
                packet = generate_random_packet(counter)
                ser.write(packet)
                print(f"Sent packet #{counter} | Checksum: {packet[75]:02X}")
                counter = (counter + 1) % 256
                time.sleep(0.1)  # 10Hz max rate
    except serial.SerialException as e:
        print(f"Serial error: {e}")
    except KeyboardInterrupt:
        print("Transmission stopped.")

if __name__ == "__main__":
    main()