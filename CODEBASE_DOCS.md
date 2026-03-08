# Turkish Model Rocketry Ground Control Station (GCS)
## Codebase Documentation

This document provides a comprehensive analysis of the Ground Control Station Web Interface developed for the Turkish Model Rocketry A4 International Category 2025 by Team VAJRA.

### 1. System Architecture
The application follows a **Daemon-Client (Service-Client) model** to ensure fault tolerance, a critical requirement for aerospace control software:
- **GCS Daemon (Backend)**: Built with Python (`gcs_backend.py`). Headless service responsible for connecting to the rocket's telemetry stream via a radio link (XBee/Serial), parsing, logging, and proxying data to the Referee Ground Station (RGS).
- **GCS Client (Frontend)**: Real-time Web UI (`gcs_dashboard.html`). Connects to the backend via WebSockets to visualize telemetry in real-time, displaying dynamic charts, recovery maps, and telemetry statuses. 

### 2. Tech Stack Setup
- **Backend**:
  - `Python 3.x`
  - `Flask` & `Flask-Cors` for API routing.
  - `Flask-SocketIO` & `eventlet` for asynchronous, real-time bidirectional WebSocket communication.
  - `pyserial` for COM port communication (RX from Rocket, TX to RGS).
- **Frontend**:
  - `HTML5 / CSS3` (Vanilla implementation with dark theme and responsive panels).
  - `Vanilla JavaScript` for DOM manipulation and Socket.IO client handling.
  - `Chart.js` for real-time telemetry plotting (Altitude, Velocity, etc.).
  - `Leaflet.js` for plotting GPS coordinates of the rocket and payload on a 2D map.

### 3. File Directory Structure 
- `/main/gcs_backend.py`: The core python server. Handles:
  - Connecting via `pyserial` to the RX (radio) and TX (RGS) ports.
  - Decoding XBee comma-separated data streams or raw 78-byte binary packets.
  - Recalculating checksums and appending derived metrics.
  - Transmitting the telemetry to all connected WebSocket clients.
- `/main/gcs_dashboard.html`: The main web interface for mission control. Includes panels for configuration, flight status, GPS mapping, metrics, and raw data logging.
- `/main/GCSInstruction.txt`: Official TEKNOFEST rules and instructions regarding GCS implementation.
- `/main/requirements.txt`: Python package requirements.
- `/Tests/`: Contains multiple Python scripts for simulating Arduino telemetry, testing TX port communication, and verifying Socket connections.

### 4. Telemetry Standard
The radio link strictly handles a fixed 78-byte binary packet or a derived comma-separated XBee string containing:
- Header bytes (`0xFF`, `0x54`, `0xFF`, `0x52`)
- Team ID & Packet Counter
- Altitude & GPS (Degrees)
- 3-Axis Gyroscope (DPS) & 3-Axis Accelerometer (G-force)
- Parachute Deployment Status & Checksums

### 5. Running the Application
1. **Install dependencies**: `pip install -r requirements.txt`
2. **Launch the backend server**: `python main/gcs_backend.py` (Typically starts on `http://127.0.0.1:5000`)
3. **Open UI**: Open `main/gcs_dashboard.html` directly in any web browser.
4. **Testing**: Run `python Tests/real_telemetry_simulator.py` to test the UI locally.