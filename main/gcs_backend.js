/**
 * GCS Backend - JavaScript (Node.js)
 * Team VAJRA - TEKNOFEST A4 International Category 2025
 *
 * This file implements the Node.js backend for the Ground Control Station (GCS).
 * It handles telemetry data reception from the rocket via serial port (XBee),
 * processes the data, and broadcasts it in real-time to connected clients using Socket.IO.
 * Converted from gcs_backend.py
 * Uses Express + Socket.IO + serialport
 */

'use strict';

const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const { SerialPort } = require('serialport');
const { ReadlineParser } = require('@serialport/parser-readline');
const { ByteLengthParser } = require('@serialport/parser-byte-length');
const struct = require('python-struct');

// ─────────────────────────────────────────────────────────────────────────────
// Global State
// ─────────────────────────────────────────────────────────────────────────────

const gcsState = {
  latestTelemetry: { status: 'Disconnected' },
  config: {
    teamId: 690600,
    targetAltitude: 8000,
    categoryMaxAltitude: 10000,
    staticMargin: 2.3,
    missionStartTime: null,
  },
  stats: {
    packetLossPercentage: 0,
    totalPacketsReceived: 0,
    totalPacketsLost: 0,
    dataRateHz: 0,
    packetRateHz: 0,
  },
  history: {
    packetTimestamps: [],        // rolling 50
    altitudeHistory: [],          // rolling 10
    lastPacketCounter: null,
    lastAltitude: 0,
    lastTimestamp: 0,
  },
  calculated: {
    deviationCoef: 0,
    reachCoef: 0,
    rocketDescentSpeed: 0,
    payloadDescentSpeed: 0,
    flightPhase: 'Standby',
    parachuteStatus: { primary: 'Not Deployed', secondary: 'Not Deployed' },
    separationStatus: 'Pending',
    gpsStatus: { rocket: 'Unknown', payload: 'Unknown' },
  },
  packetsForwarded: 0,
  lastForwardedTime: null,
};

let checksumErrors = 0;

// Serial port handles
let txSerial = null;
let rxSerial = null;
let rxParser = null;

// Auto-port config (mirrors Python global)
const autoPortConfig = {
  rxPort: null,
  txPort: '/dev/ttyACM0',
  rxBaud: 9600,
  txBaud: 19200,
  connected: false,
  mode: 'SIMPLE',
  autoDetect: true,
  detectionInterval: 5000,
};

// Port monitor interval
let portMonitorInterval = null;

// ─────────────────────────────────────────────────────────────────────────────
// Express + Socket.IO Setup
// ─────────────────────────────────────────────────────────────────────────────

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*', methods: ['GET', 'POST'] },
  transports: ['websocket', 'polling'],
});

app.use(cors({ origin: '*' }));
app.use(express.json());

// ─────────────────────────────────────────────────────────────────────────────
// Helper Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Clamp array to a max length by shifting from the front.
 */
function rollingPush(arr, value, maxLen) {
  arr.push(value);
  while (arr.length > maxLen) arr.shift();
}

/**
 * Recursively convert Buffer / Uint8Array values to hex strings for JSON.
 */
function cleanForJson(data) {
  if (Buffer.isBuffer(data) || data instanceof Uint8Array) {
    return Buffer.from(data).toString('hex');
  }
  if (Array.isArray(data)) return data.map(cleanForJson);
  if (data !== null && typeof data === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(data)) out[k] = cleanForJson(v);
    return out;
  }
  return data;
}

// ─────────────────────────────────────────────────────────────────────────────
// Flight Phase / Parachute Decoding
// ─────────────────────────────────────────────────────────────────────────────

function decodeFlightPhase(statusCode) {
  const phases = {
    0: 'Standby',
    1: 'Armed',
    2: 'Flight/Ascent',
    3: 'Apogee',
    4: 'Descent/Recovery',
    5: 'Landing',
  };
  return phases[statusCode] ?? `Unknown (${statusCode})`;
}

function decodeParachuteStatus(statusCode) {
  if (statusCode === 1) return { primary: 'Not Deployed', secondary: 'Not Deployed' };
  if (statusCode === 2) return { primary: 'Not Deployed', secondary: 'Not Deployed' };
  if (statusCode === 3) return { primary: 'Deployed',     secondary: 'Not Deployed' };
  if (statusCode === 4) return { primary: 'Deployed',     secondary: 'Deployed' };
  return { primary: 'Unknown', secondary: 'Unknown' };
}

function calculateGpsStatus(lat, lon, alt) {
  return lat !== 0 && lon !== 0 && alt > 0 ? 'Active' : 'No Fix';
}

function calculateIntegrationBonus(deviationCoef, reachCoef) {
  const base = 100;
  const devBonus = Math.floor(deviationCoef * 50);
  const reachBonus = Math.floor(reachCoef * 50);
  return Math.min(base + devBonus + reachBonus, 200);
}

// ─────────────────────────────────────────────────────────────────────────────
// Packet Construction
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Build the 78-byte RGS binary packet (mirrors create_enhanced_tx_packet).
 * Header: FF FF 54 52 | TeamID | Counter | 17×float32-LE | Status | Checksum | 0D 0A
 */
function createTxPacket(telemetry) {
  const buf = Buffer.alloc(78, 0);
  let offset = 0;

  // Header
  buf[offset++] = 0xff;
  buf[offset++] = 0xff;
  buf[offset++] = 0x54;
  buf[offset++] = 0x52;

  // Team ID & packet counter (single byte each, masked to 0–255)
  buf[offset++] = (telemetry.team_id ?? 690600) & 0xff;
  buf[offset++] = (telemetry.packet_counter ?? 0) & 0xff;

  // 17 float32-LE fields
  const floatFields = [
    'altitude_agl', 'rocket_gps_altitude', 'rocket_latitude', 'rocket_longitude',
    'payload_gps_altitude', 'payload_latitude', 'payload_longitude',
    'stage_gps_altitude', 'stage_latitude', 'stage_longitude',
    'gyro_x', 'gyro_y', 'gyro_z',
    'accel_x', 'accel_y', 'accel_z',
    'angle',
  ];

  for (const field of floatFields) {
    buf.writeFloatLE(telemetry[field] ?? 0.0, offset);
    offset += 4;
  }

  // Status byte
  buf[offset++] = (telemetry.status_code ?? 0) & 0xff;

  // Checksum: sum of bytes [4..74] mod 256
  let checksum = 0;
  for (let i = 4; i < 75; i++) checksum = (checksum + buf[i]) & 0xff;
  buf[offset++] = checksum;

  // Footer
  buf[offset++] = 0x0d;
  buf[offset]   = 0x0a;

  return buf;
}

// ─────────────────────────────────────────────────────────────────────────────
// Packet Parsing
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parse a 78-byte Buffer into a telemetry object.
 * Returns null on validation failure.
 */
function parse78BytePacket(buf) {
  if (!Buffer.isBuffer(buf) || buf.length !== 78) return null;

  // Validate header
  if (buf[0] !== 0xff || buf[1] !== 0xff || buf[2] !== 0x54 || buf[3] !== 0x52) {
    console.warn(`[WARN] Invalid header: ${buf.slice(0, 4).toString('hex')}`);
    return null;
  }

  const data = {};
  data.raw_hex = buf.toString('hex').toUpperCase().match(/.{2}/g).join(' ');
  data.team_id = buf[4];
  data.packet_counter = buf[5];

  const floatNames = [
    'altitude_agl', 'rocket_gps_altitude', 'rocket_latitude', 'rocket_longitude',
    'payload_gps_altitude', 'payload_latitude', 'payload_longitude',
    'stage_gps_altitude', 'stage_latitude', 'stage_longitude',
    'gyro_x', 'gyro_y', 'gyro_z',
    'accel_x', 'accel_y', 'accel_z',
    'angle',
  ];

  let floatOffset = 6;
  for (const name of floatNames) {
    data[name] = buf.readFloatLE(floatOffset);
    floatOffset += 4;
  }

  data.status_code = buf[74];
  data.checksum = buf[75];

  // Footer
  if (buf[76] !== 0x0d || buf[77] !== 0x0a) {
    console.warn('[WARN] Invalid footer bytes');
  }

  // Validate checksum
  let calcChecksum = 0;
  for (let i = 4; i < 75; i++) calcChecksum = (calcChecksum + buf[i]) & 0xff;
  if (calcChecksum !== data.checksum) {
    checksumErrors++;
    console.warn(`[WARN] Checksum mismatch: calc=0x${calcChecksum.toString(16).toUpperCase()}, recv=0x${data.checksum.toString(16).toUpperCase()}`);
  }

  return data;
}

/**
 * Parse the 17-field comma-separated XBee string.
 * Format: altitude,gnssAltitude,lat,lon,0,0,0,0,0,0,gyroX,gyroY,gyroZ,accX,accY,accZ,angleX
 */
function parseXbeeString(line) {
  console.log(`[RX] Received XBee String: "${line}"`);
  const parts = line.trim().split(',');

  if (parts.length !== 17) {
    console.error(`[ERROR] Invalid XBee format. Expected 17 values, got ${parts.length}`);
    return null;
  }

  const toFloat = (s) => { const v = parseFloat(s); return isNaN(v) ? 0.0 : v; };
  const toInt   = (s) => { const v = parseInt(s, 10); return isNaN(v) ? 0 : v; };

  return {
    team_id: 690600,
    packet_counter: (gcsState.stats.totalPacketsReceived + 1) & 0xff,
    altitude_agl:          toFloat(parts[0]),
    rocket_gps_altitude:   toFloat(parts[1]),
    rocket_latitude:       toFloat(parts[2]),
    rocket_longitude:      toFloat(parts[3]),
    payload_gps_altitude:  toFloat(parts[4]),
    payload_latitude:      toFloat(parts[5]),
    payload_longitude:     toFloat(parts[6]),
    stage_gps_altitude:    toFloat(parts[7]),
    stage_latitude:        toFloat(parts[8]),
    stage_longitude:       toFloat(parts[9]),
    gyro_x:  toFloat(parts[10]),
    gyro_y:  toFloat(parts[11]),
    gyro_z:  toFloat(parts[12]),
    accel_x: toFloat(parts[13]),
    accel_y: toFloat(parts[14]),
    accel_z: toFloat(parts[15]),
    angle:   toFloat(parts[16]),
    status_code: 4,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Calculations & State Updates
// ─────────────────────────────────────────────────────────────────────────────

function updateCalculations(telemetry) {
  const now = Date.now() / 1000; // seconds

  if (gcsState.config.missionStartTime === null) {
    gcsState.config.missionStartTime = now;
  }

  // Rolling packet timestamp buffer (max 50)
  rollingPush(gcsState.history.packetTimestamps, now, 50);

  // Data rate
  const ts = gcsState.history.packetTimestamps;
  if (ts.length > 1) {
    const timeDiff = ts[ts.length - 1] - ts[0];
    if (timeDiff > 0) {
      const hz = Math.round(((ts.length - 1) / timeDiff) * 10) / 10;
      gcsState.stats.dataRateHz = hz;
      gcsState.stats.packetRateHz = hz;
    }
  }

  // Packet loss
  const lastCounter = gcsState.history.lastPacketCounter;
  const currentCounter = telemetry.packet_counter;

  if (lastCounter !== null && currentCounter !== undefined) {
    gcsState.stats.totalPacketsReceived++;
    let lost = currentCounter > lastCounter
      ? currentCounter - lastCounter - 1
      : (255 - lastCounter) + currentCounter;
    if (lost >= 0 && lost < 50) gcsState.stats.totalPacketsLost += lost;
    const expected = gcsState.stats.totalPacketsReceived + gcsState.stats.totalPacketsLost;
    if (expected > 0) {
      gcsState.stats.packetLossPercentage =
        Math.round((gcsState.stats.totalPacketsLost / expected) * 10000) / 100;
    }
  }
  gcsState.history.lastPacketCounter = currentCounter;

  // Altitude history + descent speed
  const currentAlt = telemetry.altitude_agl ?? 0;
  rollingPush(gcsState.history.altitudeHistory, { altitude: currentAlt, timestamp: now }, 10);

  const ah = gcsState.history.altitudeHistory;
  if (ah.length >= 2) {
    const recent = ah[ah.length - 1];
    const prev   = ah[ah.length - 2];
    const dt = recent.timestamp - prev.timestamp;
    if (dt > 0) {
      const speed = Math.round(((prev.altitude - recent.altitude) / dt) * 10) / 10;
      if (speed > 0) {
        gcsState.calculated.rocketDescentSpeed = speed;
        gcsState.calculated.payloadDescentSpeed = speed;
      }
    }
  }

  // Performance coefficients
  const target = gcsState.config.targetAltitude;
  const maxAlt = gcsState.config.categoryMaxAltitude;
  if (target > 0) {
    gcsState.calculated.deviationCoef =
      Math.round(Math.max(0, 1 - Math.abs(currentAlt - target) / target) * 1000) / 1000;
  }
  if (maxAlt > 0) {
    gcsState.calculated.reachCoef = Math.round((currentAlt / maxAlt) * 1000) / 1000;
  }

  // Flight status
  const sc = telemetry.status_code ?? 0;
  gcsState.calculated.flightPhase = decodeFlightPhase(sc);
  gcsState.calculated.parachuteStatus = decodeParachuteStatus(sc);
  if (sc >= 3 && currentAlt > 1000) gcsState.calculated.separationStatus = 'Confirmed';

  // GPS status
  gcsState.calculated.gpsStatus = {
    rocket:  calculateGpsStatus(telemetry.rocket_latitude ?? 0,  telemetry.rocket_longitude ?? 0,  telemetry.rocket_gps_altitude ?? 0),
    payload: calculateGpsStatus(telemetry.payload_latitude ?? 0, telemetry.payload_longitude ?? 0, telemetry.payload_gps_altitude ?? 0),
  };

  // Merge into latestTelemetry
  Object.assign(gcsState.latestTelemetry, telemetry);
  gcsState.latestTelemetry.status = 'Receiving Data';
  gcsState.latestTelemetry.timestamp = now;

  const missionTime = Math.floor(now - gcsState.config.missionStartTime);

  return {
    ...telemetry,
    communication: {
      rx_tx_packets: `${gcsState.stats.totalPacketsReceived} / ${gcsState.stats.totalPacketsReceived}`,
      data_rate_hz: gcsState.stats.dataRateHz,
      packet_rate_hz: gcsState.stats.packetRateHz,
      packet_loss_percentage: gcsState.stats.packetLossPercentage,
    },
    flight_status: {
      phase:               gcsState.calculated.flightPhase,
      parachute_primary:   gcsState.calculated.parachuteStatus.primary,
      parachute_secondary: gcsState.calculated.parachuteStatus.secondary,
      separation:          gcsState.calculated.separationStatus,
    },
    descent_speeds: {
      rocket:  gcsState.calculated.rocketDescentSpeed,
      payload: gcsState.calculated.payloadDescentSpeed,
    },
    locator_systems: {
      rocket_gps:  gcsState.calculated.gpsStatus.rocket,
      payload_gps: gcsState.calculated.gpsStatus.payload,
    },
    performance: {
      target_altitude:  target,
      actual_altitude:  currentAlt,
      deviation_coef:   gcsState.calculated.deviationCoef,
      reach_coef:       gcsState.calculated.reachCoef,
    },
    static_margin:      gcsState.config.staticMargin,
    integration_bonus:  calculateIntegrationBonus(gcsState.calculated.deviationCoef, gcsState.calculated.reachCoef),
    mission_time:       missionTime,
    statistics: {
      packets_sent:    gcsState.stats.totalPacketsReceived,
      packet_loss:     gcsState.stats.packetLossPercentage,
      checksum_errors: checksumErrors,
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// TX Port
// ─────────────────────────────────────────────────────────────────────────────

function sendToTxPort(telemetry) {
  if (!txSerial || !autoPortConfig.connected) {
    console.log(`[DEBUG] TX send skipped – txSerial=${!!txSerial}, connected=${autoPortConfig.connected}`);
    return false;
  }
  try {
    const packet = createTxPacket(telemetry);
    txSerial.write(packet, (err) => {
      if (err) {
        console.error(`[ERROR] TX write error: ${err.message}`);
        autoPortConfig.connected = false;
      }
    });
    const preview = packet.slice(0, 20).toString('hex').toUpperCase().match(/.{2}/g).join(' ');
    console.log(`[TX] Sent 78B @ ${autoPortConfig.txBaud} baud: ${preview}...`);
    return true;
  } catch (err) {
    console.error(`[ERROR] TX send failed: ${err.message}`);
    autoPortConfig.connected = false;
    return false;
  }
}

function sendToRxPort(command) {
  if (!rxSerial || !autoPortConfig.rxPort) return false;
  try {
    rxSerial.write(Buffer.from(command, 'utf8'));
    console.log(`[RX] Sent command: ${command.trim()}`);
    return true;
  } catch (err) {
    console.error(`[ERROR] RX send failed: ${err.message}`);
    return false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Packet Callback
// ─────────────────────────────────────────────────────────────────────────────

function onPacket(data) {
  try {
    gcsState.stats.totalPacketsReceived++;
    const now = Date.now() / 1000;
    rollingPush(gcsState.history.packetTimestamps, now, 50);
    if (!gcsState.config.missionStartTime) gcsState.config.missionStartTime = now;

    console.log(`[INFO] XBee telemetry: Team ${data.team_id}, Counter: ${data.packet_counter}`);
    console.log(`[TELEMETRY] Alt: ${(data.altitude_agl ?? 0).toFixed(1)}m | GPS: ${data.rocket_latitude},${data.rocket_longitude}`);

    const structured = updateCalculations(data);

    if (autoPortConfig.connected) {
      if (sendToTxPort(data)) {
        gcsState.packetsForwarded++;
        gcsState.lastForwardedTime = now;
        console.log(`[FORWARD] Packet forwarded to TX (Total: ${gcsState.packetsForwarded})`);
      }
    }

    const cleaned = cleanForJson(structured);
    io.emit('telemetry', cleaned);
    console.log('[DEBUG] Telemetry emitted via Socket.IO');
  } catch (err) {
    console.error(`[ERROR] onPacket: ${err.message}`);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Serial Port Management
// ─────────────────────────────────────────────────────────────────────────────

/**
 * List all available serial ports (mirrors get_usb_serial_ports / detect_arduino_ports).
 */
async function getUsbSerialPorts() {
  const all = await SerialPort.list();
  return all.map((p) => ({
    device:       p.path,
    description:  p.manufacturer ?? p.friendlyName ?? '',
    hwid:         p.pnpId ?? '',
    manufacturer: p.manufacturer ?? '',
    product:      p.friendlyName ?? '',
    vid:          p.vendorId ?? null,
    pid:          p.productId ?? null,
  }));
}

async function detectArduinoPorts() {
  const all = await getUsbSerialPorts();
  const indicators = ['ARDUINO','CH340','CH341','CP210','FTDI','PL2303','USB-SERIAL','USB SERIAL'];
  return all.filter((p) => {
    const d = (p.description + p.hwid).toUpperCase();
    return indicators.some((ind) => d.includes(ind));
  });
}

/**
 * Open a new RX (XBee) serial connection and wire up the line parser.
 */
function startXbeeListener(port, baud) {
  if (rxSerial) {
    try { rxSerial.close(); } catch (_) {}
    rxSerial = null;
    rxParser = null;
  }

  console.log(`[XBEE] Opening ${port} @ ${baud} baud`);
  rxSerial = new SerialPort({ path: port, baudRate: baud, autoOpen: false });
  rxParser = rxSerial.pipe(new ReadlineParser({ delimiter: '\n' }));

  rxSerial.open((err) => {
    if (err) {
      console.error(`[ERROR] Cannot open RX port ${port}: ${err.message}`);
      return;
    }
    console.log(`[XBEE] Connected to ${port}`);
  });

  rxParser.on('data', (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    console.log(`[XBEE] Raw line: ${trimmed}`);
    const parsed = parseXbeeString(trimmed);
    if (parsed) onPacket(parsed);
    else console.warn('[XBEE] Failed to parse line');
  });

  rxSerial.on('error', (err) => {
    console.error(`[ERROR] RX serial error: ${err.message}`);
  });

  rxSerial.on('close', () => {
    console.log('[XBEE] RX port closed');
  });
}

/**
 * Open a new binary (78-byte packet) serial connection.
 */
function startBinaryListener(port, baud) {
  if (rxSerial) {
    try { rxSerial.close(); } catch (_) {}
    rxSerial = null;
  }

  console.log(`[SERIAL] Opening ${port} @ ${baud} baud`);
  rxSerial = new SerialPort({ path: port, baudRate: baud, autoOpen: false });

  // Accumulate raw bytes and scan for 78-byte frames
  let packetBuffer = Buffer.alloc(0);

  rxSerial.on('data', (chunk) => {
    packetBuffer = Buffer.concat([packetBuffer, chunk]);
    const preview = chunk.slice(0, 20).toString('hex').toUpperCase();
    console.log(`[RAW] ${port}: ${chunk.length} bytes – ${preview}${chunk.length > 20 ? '...' : ''}`);

    while (packetBuffer.length >= 78) {
      // Find 0xFF 0xFF sync header
      let startIdx = -1;
      for (let i = 0; i < packetBuffer.length - 1; i++) {
        if (packetBuffer[i] === 0xff && packetBuffer[i + 1] === 0xff) {
          startIdx = i;
          break;
        }
      }

      if (startIdx === -1) { packetBuffer = Buffer.alloc(0); break; }
      if (packetBuffer.length < startIdx + 78) break; // wait for more

      const packet = packetBuffer.slice(startIdx, startIdx + 78);
      if (packet[76] === 0x0d && packet[77] === 0x0a) {
        const parsed = parse78BytePacket(packet);
        if (parsed) {
          console.log(`[PARSED] Packet ${parsed.packet_counter} from ${port}`);
          onPacket(parsed);
        }
      }
      packetBuffer = packetBuffer.slice(startIdx + 78);
    }
  });

  rxSerial.open((err) => {
    if (err) console.error(`[ERROR] Cannot open binary RX port ${port}: ${err.message}`);
    else console.log(`[SERIAL] Connected to ${port}`);
  });

  rxSerial.on('error', (err) => console.error(`[ERROR] Binary RX: ${err.message}`));
  rxSerial.on('close', () => console.log('[SERIAL] Binary RX port closed'));
}

/**
 * Open TX port for forwarding telemetry.
 */
function openTxPort(port, baud) {
  if (txSerial) {
    try { txSerial.close(); } catch (_) {}
    txSerial = null;
  }

  txSerial = new SerialPort({
    path: port, baudRate: baud,
    dataBits: 8, parity: 'none', stopBits: 1,
    autoOpen: false,
  });

  txSerial.open((err) => {
    if (err) {
      console.error(`[ERROR] Cannot open TX port ${port}: ${err.message}`);
      autoPortConfig.connected = false;
    } else {
      autoPortConfig.connected = true;
      console.log(`[AUTO] TX connected to ${port} @ ${baud} baud`);
    }
  });

  txSerial.on('error', (err) => {
    console.error(`[ERROR] TX serial: ${err.message}`);
    autoPortConfig.connected = false;
  });
  txSerial.on('close', () => {
    console.log('[AUTO] TX port closed');
    autoPortConfig.connected = false;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Auto-Connect / Monitor
// ─────────────────────────────────────────────────────────────────────────────

async function autoConnectPorts() {
  const arduinoPorts = await detectArduinoPorts();
  if (!arduinoPorts.length) {
    console.log('[AUTO] No Arduino ports detected');
    return false;
  }

  console.log(`[AUTO] Found ${arduinoPorts.length} Arduino port(s):`);
  arduinoPorts.forEach((p) => console.log(`  - ${p.device}: ${p.description}`));

  // Assign RX to first available
  if (!autoPortConfig.rxPort && arduinoPorts[0]) {
    autoPortConfig.rxPort = arduinoPorts[0].device;
    console.log(`[AUTO] Selected RX port: ${autoPortConfig.rxPort}`);
  }

  // Assign TX to a different port if available
  const txCandidate = arduinoPorts.find((p) => p.device !== autoPortConfig.rxPort);
  if (txCandidate) {
    autoPortConfig.txPort = txCandidate.device;
    console.log(`[AUTO] Selected TX port: ${autoPortConfig.txPort}`);
  }

  if (autoPortConfig.txPort === autoPortConfig.rxPort) {
    console.warn('[AUTO] RX and TX ports are the same – TX forwarding disabled');
    autoPortConfig.txPort = null;
    autoPortConfig.connected = false;
  }

  return !!autoPortConfig.rxPort;
}

async function initializeAutoPorts() {
  const found = await autoConnectPorts();
  if (!found) {
    console.log('[AUTO] No suitable ports – will retry later');
    return false;
  }

  if (autoPortConfig.rxPort) {
    startXbeeListener(autoPortConfig.rxPort, autoPortConfig.rxBaud);
  }

  if (autoPortConfig.txPort) {
    openTxPort(autoPortConfig.txPort, autoPortConfig.txBaud);
  } else {
    console.log('[AUTO] No TX port – forwarding disabled');
  }

  return !!autoPortConfig.rxPort;
}

function startPortMonitor() {
  if (portMonitorInterval) clearInterval(portMonitorInterval);
  portMonitorInterval = setInterval(async () => {
    try {
      const allPaths = (await SerialPort.list()).map((p) => p.path);

      let needReinit = false;
      if (autoPortConfig.rxPort && !allPaths.includes(autoPortConfig.rxPort)) {
        console.warn(`[MONITOR] RX port ${autoPortConfig.rxPort} gone`);
        autoPortConfig.rxPort = null; needReinit = true;
      }
      if (autoPortConfig.txPort && !allPaths.includes(autoPortConfig.txPort)) {
        console.warn(`[MONITOR] TX port ${autoPortConfig.txPort} gone`);
        autoPortConfig.txPort = null; autoPortConfig.connected = false; needReinit = true;
      }

      if (needReinit) {
        console.log('[MONITOR] Attempting auto-reconnect...');
        await initializeAutoPorts();
      }
    } catch (err) {
      console.error(`[MONITOR] Error: ${err.message}`);
    }
  }, autoPortConfig.detectionInterval);
}

// ─────────────────────────────────────────────────────────────────────────────
// API Routes  (mirror all Flask routes from gcs_backend.py)
// ─────────────────────────────────────────────────────────────────────────────

// GET /api/data
app.get('/api/data', (_req, res) => res.json(gcsState.latestTelemetry));

// GET /api/ports
app.get('/api/ports', async (_req, res) => {
  try {
    const all = await getUsbSerialPorts();
    const arduino = await detectArduinoPorts();
    res.json({ all_ports: all, arduino_ports: arduino, auto_config: autoPortConfig });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /api/auto-detect
app.post('/api/auto-detect', async (_req, res) => {
  try {
    const ok = await initializeAutoPorts();
    if (ok) {
      res.json({
        status: 'success',
        message: `Auto-detected RX: ${autoPortConfig.rxPort}, TX: ${autoPortConfig.txPort}`,
        config: autoPortConfig,
        arduino_ports: await detectArduinoPorts(),
      });
    } else {
      res.json({ status: 'warning', message: 'No Arduino ports detected', available_ports: await getUsbSerialPorts() });
    }
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET/POST /api/config
app.route('/api/config')
  .get((_req, res) => res.json(gcsState.config))
  .post((req, res) => {
    const newCfg = req.body;
    if (newCfg.target_altitude !== undefined) {
      if (typeof newCfg.target_altitude !== 'number' || newCfg.target_altitude <= 0) {
        return res.status(400).json({ error: 'Invalid target_altitude' });
      }
    }
    Object.assign(gcsState.config, newCfg);
    console.log('[INFO] Config updated:', gcsState.config);
    res.json({ status: 'success', config: gcsState.config });
  });

// POST /api/connect
app.post('/api/connect', async (req, res) => {
  try {
    if (req.body.auto) {
      const ok = await initializeAutoPorts();
      if (ok) return res.json({ status: 'success', message: `Auto-connected`, config: autoPortConfig });
      return res.status(500).json({ error: 'Auto-connection failed' });
    }

    const port = req.body.port;
    const baud = parseInt(req.body.baud ?? 19200, 10);
    if (!port || !(port.startsWith('/dev/') || port.startsWith('COM'))) {
      return res.status(400).json({ error: 'Invalid port' });
    }

    startBinaryListener(port, baud);
    gcsState.latestTelemetry.status = `Connected to ${port} @ ${baud}`;
    res.json({ status: 'success', message: `Connected to ${port} @ ${baud}` });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /api/disconnect
app.post('/api/disconnect', (_req, res) => {
  try {
    if (rxSerial) { try { rxSerial.close(); } catch (_) {} rxSerial = null; }
    gcsState.latestTelemetry.status = 'Disconnected';
    res.json({ status: 'success', message: 'Disconnected' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Control endpoints ────────────────────────────────────────────────────────
const CONTROL_COMMANDS = {
  'zero-altitude':    'ZERO_ALT\n',
  'reset-counters':   'RESET_CNT\n',
  'main-activate':    'MAIN_ACTIVATE\n',
  'main-release':     'MAIN_RELEASE\n',
  'backup-activate':  'BACKUP_ACTIVATE\n',
  'backup-release':   'BACKUP_RELEASE\n',
  'parachute-status': 'CHUTE_STATUS\n',
};

for (const [endpoint, cmd] of Object.entries(CONTROL_COMMANDS)) {
  app.post(`/api/control/${endpoint}`, (_req, res) => {
    if (sendToRxPort(cmd)) {
      res.json({ status: 'success', message: `${endpoint} command sent` });
    } else {
      res.status(500).json({ error: 'Failed to send command – RX port not connected' });
    }
  });
}

// ── TX port management ───────────────────────────────────────────────────────
app.post('/api/tx/connect', async (_req, res) => {
  const ok = await initializeAutoPorts();
  if (ok) res.json({ status: 'success', message: `TX connected`, config: autoPortConfig });
  else res.status(500).json({ error: 'Failed to auto-connect' });
});

app.post('/api/tx/disconnect', (_req, res) => {
  if (rxSerial) { try { rxSerial.close(); } catch (_) {} rxSerial = null; }
  if (txSerial) { try { txSerial.close(); } catch (_) {} txSerial = null; }
  autoPortConfig.connected = false;
  autoPortConfig.rxPort = null;
  autoPortConfig.txPort = null;
  res.json({ status: 'success', message: 'All ports disconnected' });
});

app.get('/api/tx/status', (_req, res) => res.json(autoPortConfig));

app.post('/api/tx/mode', (req, res) => {
  const mode = req.body.mode;
  if (!['SIMPLE', 'FULL', 'COMMAND'].includes(mode)) {
    return res.status(400).json({ error: 'Invalid mode. Use SIMPLE, FULL, or COMMAND' });
  }
  autoPortConfig.mode = mode;
  res.json({ status: 'success', message: `TX mode set to ${mode}`, config: autoPortConfig });
});

// GET /api/ports/status
app.get('/api/ports/status', (_req, res) => {
  const rxConnected = !!(rxSerial && rxSerial.isOpen);
  res.json({
    rx: { connected: rxConnected, port: autoPortConfig.rxPort ?? 'Unknown', baud: autoPortConfig.rxBaud },
    tx: { connected: autoPortConfig.connected, port: autoPortConfig.txPort ?? 'Unknown', baud: autoPortConfig.txBaud, mode: autoPortConfig.mode },
    auto_config: autoPortConfig,
    forwarding: {
      enabled:           rxConnected && autoPortConfig.connected,
      packets_forwarded: gcsState.packetsForwarded,
      last_forwarded:    gcsState.lastForwardedTime,
    },
  });
});

// GET /api/debug/tx-status
app.get('/api/debug/tx-status', (_req, res) => {
  const st = {
    tx_serial_exists:  !!txSerial,
    auto_port_config:  { ...autoPortConfig },
    tx_port_available: !!autoPortConfig.txPort,
    connected_flag:    autoPortConfig.connected,
  };
  if (txSerial) {
    st.tx_serial_port = txSerial.path;
    st.tx_serial_open = txSerial.isOpen;
  }
  res.json(st);
});

// POST /api/test_telemetry  (used by test scripts)
app.post('/api/test_telemetry', (req, res) => {
  try {
    const testData = req.body && Object.keys(req.body).length > 0 ? req.body : {
      team_id: 690600, packet_counter: 1,
      altitude_agl: 1234.5, rocket_gps_altitude: 1236.5,
      rocket_latitude: 41.015234, rocket_longitude: 28.979530,
      payload_gps_altitude: 115.7, payload_latitude: 41.015240, payload_longitude: 28.979535,
      stage_gps_altitude: 0, stage_latitude: 0, stage_longitude: 0,
      gyro_x: 0.26, gyro_y: -0.11, gyro_z: 0.61,
      accel_x: -0.09, accel_y: 0.10, accel_z: -0.90,
      angle: 15.8, status_code: 4,
    };
    onPacket(testData);
    res.json({ status: 'success', message: 'Test telemetry injected', data: testData });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Socket.IO Events
// ─────────────────────────────────────────────────────────────────────────────

io.on('connection', (socket) => {
  console.log(`[INFO] Web client connected: ${socket.id}`);
  if (gcsState.latestTelemetry.status !== 'Disconnected') {
    socket.emit('telemetry', cleanForJson(gcsState.latestTelemetry));
  }

  socket.on('disconnect', () => console.log(`[INFO] Web client disconnected: ${socket.id}`));

  socket.on('telemetry_request', () => {
    console.log(`[INFO] telemetry_request from ${socket.id}`);
    if (gcsState.latestTelemetry.status !== 'Disconnected') {
      socket.emit('telemetry', cleanForJson(gcsState.latestTelemetry));
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Start
// ─────────────────────────────────────────────────────────────────────────────

const PORT = 5000;
server.listen(PORT, '127.0.0.1', async () => {
  console.log(`🚀 TEKNOFEST GCS Backend (Node.js) on http://127.0.0.1:${PORT}`);
  console.log('📡 Auto-port detection enabled for RX→TX telemetry forwarding');
  console.log('\n🔌 Available endpoints:');
  console.log('   POST /api/auto-detect   GET  /api/ports');
  console.log('   POST /api/connect       POST /api/disconnect');
  console.log('   GET  /api/ports/status  POST /api/tx/mode');
  console.log('   POST /api/test_telemetry');
  console.log('   WebSocket: Socket.IO at ws://127.0.0.1:5000\n');

  console.log('[INIT] Starting auto-port detection...');
  const ok = await initializeAutoPorts();
  if (ok) {
    console.log(`[SUCCESS] RX: ${autoPortConfig.rxPort} | TX: ${autoPortConfig.txPort}`);
  } else {
    console.log('[WARNING] No ports found – will retry via port monitor');
  }

  startPortMonitor();
  console.log('[INIT] Port monitor started\n');
});

module.exports = { app, server, io, onPacket, createTxPacket, parse78BytePacket, parseXbeeString };