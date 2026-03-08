#!/usr/bin/env python3
"""
Real Telemetry Simulator
Simulates realistic rocket telemetry data and sends it to the backend.
"""

import requests
import time
import random
import math

def create_realistic_telemetry():
    """Create realistic telemetry data that simulates a rocket flight."""
    
    # Simulate a rocket flight profile
    mission_time = int(time.time() % 3600)  # Simulate mission time
    
    # Altitude profile (launch -> apogee -> descent)
    if mission_time < 30:  # Launch phase
        altitude = 100 + (mission_time * 50)  # Rapid ascent
    elif mission_time < 60:  # Apogee phase
        altitude = 1500 + (mission_time - 30) * 10  # Slower ascent
    else:  # Descent phase
        altitude = max(0, 1800 - (mission_time - 60) * 20)  # Descent
    
    # GPS coordinates (simulate drift)
    base_lat = 41.015234
    base_lon = 28.979530
    lat_drift = math.sin(mission_time * 0.1) * 0.0001
    lon_drift = math.cos(mission_time * 0.1) * 0.0001
    
    # IMU data (realistic for rocket flight)
    if mission_time < 30:  # Launch - high acceleration
        accel_z = -15.0 + random.uniform(-2, 2)  # High G during launch
        gyro_x = random.uniform(-5, 5)  # Some rotation
        gyro_y = random.uniform(-3, 3)
        gyro_z = random.uniform(-2, 2)
    elif mission_time < 60:  # Coast - lower acceleration
        accel_z = -10.0 + random.uniform(-1, 1)
        gyro_x = random.uniform(-2, 2)
        gyro_y = random.uniform(-1, 1)
        gyro_z = random.uniform(-0.5, 0.5)
    else:  # Descent - parachute deployment
        accel_z = -2.0 + random.uniform(-0.5, 0.5)  # Slow descent
        gyro_x = random.uniform(-1, 1)
        gyro_y = random.uniform(-0.5, 0.5)
        gyro_z = random.uniform(-0.2, 0.2)
    
    # Flight status based on mission time
    if mission_time < 30:
        status_code = 1  # Launch
        flight_phase = "Launch"
    elif mission_time < 60:
        status_code = 2  # Coast
        flight_phase = "Coast"
    else:
        status_code = 3  # Descent
        flight_phase = "Descent"
    
    telemetry = {
        "team_id": 142,
        "packet_counter": mission_time,
        "altitude_agl": altitude,
        "rocket_gps_altitude": altitude + 20.0,
        "rocket_latitude": base_lat + lat_drift,
        "rocket_longitude": base_lon + lon_drift,
        "payload_gps_altitude": altitude + 15.0,
        "payload_latitude": base_lat + lat_drift + 0.00001,
        "payload_longitude": base_lon + lon_drift + 0.00001,
        "stage_gps_altitude": altitude + 10.0,
        "stage_latitude": base_lat + lat_drift - 0.00001,
        "stage_longitude": base_lon + lon_drift - 0.00001,
        "gyro_x": gyro_x,
        "gyro_y": gyro_y,
        "gyro_z": gyro_z,
        "accel_x": random.uniform(-0.5, 0.5),
        "accel_y": random.uniform(-0.5, 0.5),
        "accel_z": accel_z,
        "angle": random.uniform(0, 45),
        "status_code": status_code,
        "mission_time": mission_time,
        "flight_phase": flight_phase
    }
    
    return telemetry

def send_real_telemetry():
    """Send realistic telemetry data to the backend."""
    print("🚀 Real Telemetry Simulator")
    print("=" * 50)
    print("📡 Sending realistic rocket telemetry data...")
    print("🎯 This simulates a real rocket flight profile:")
    print("   - Launch phase (0-30s): High acceleration")
    print("   - Coast phase (30-60s): Apogee")
    print("   - Descent phase (60s+): Parachute deployment")
    print()
    
    try:
        # Send telemetry data every second
        for i in range(120):  # 2 minutes of simulation
            telemetry = create_realistic_telemetry()
            
            # Send to backend
            response = requests.post(
                "http://127.0.0.1:5000/api/test_telemetry",
                json=telemetry,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                print(f"📡 Packet {telemetry['packet_counter']:3d}: "
                      f"Alt={telemetry['altitude_agl']:6.1f}m, "
                      f"Phase={telemetry['flight_phase']:8s}, "
                      f"Status={telemetry['status_code']}")
            else:
                print(f"❌ Failed to send telemetry: {response.status_code}")
            
            time.sleep(1)  # Send every second
            
    except KeyboardInterrupt:
        print("\n⏹️  Simulation stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    send_real_telemetry() 