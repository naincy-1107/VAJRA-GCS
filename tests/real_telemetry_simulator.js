#!/usr/bin/env node
/**
 * real_telemetry_simulator.js
 * Simulates realistic rocket telemetry and POSTs it to the JS backend.
 * This simulator generates mock telemetry data mimicking real rocket flight
 * and sends it to the GCS backend for testing purposes.
 * JS port of Tests/real_telemetry_simulator.py
 */

'use strict';

const http = require('http');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function postJson(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      { hostname: '127.0.0.1', port: 5000, path, method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => {
        let buf = '';
        res.on('data', (c) => (buf += c));
        res.on('end', () => { try { resolve({ status: res.statusCode, body: JSON.parse(buf) }); } catch { resolve({ status: res.statusCode, body: buf }); } });
      }
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

// ─── Telemetry Generator ─────────────────────────────────────────────────────

function createRealisticTelemetry(packetIndex) {
  const t = packetIndex; // seconds into simulation

  // Altitude profile
  let altitude;
  if (t < 30)       altitude = 100 + t * 50;           // rapid ascent
  else if (t < 60)  altitude = 1500 + (t - 30) * 10;  // slower ascent to apogee
  else              altitude = Math.max(0, 1800 - (t - 60) * 20); // descent

  // GPS drift
  const baseLat = 41.015234, baseLon = 28.979530;
  const latDrift = Math.sin(t * 0.1) * 0.0001;
  const lonDrift = Math.cos(t * 0.1) * 0.0001;

  // IMU
  let accelZ, gyroX, gyroY, gyroZ;
  const rand = (lo, hi) => lo + Math.random() * (hi - lo);
  if (t < 30) {
    accelZ = -15.0 + rand(-2, 2);  gyroX = rand(-5, 5);  gyroY = rand(-3, 3);  gyroZ = rand(-2, 2);
  } else if (t < 60) {
    accelZ = -10.0 + rand(-1, 1);  gyroX = rand(-2, 2);  gyroY = rand(-1, 1);  gyroZ = rand(-0.5, 0.5);
  } else {
    accelZ = -2.0 + rand(-0.5, 0.5); gyroX = rand(-1, 1); gyroY = rand(-0.5, 0.5); gyroZ = rand(-0.2, 0.2);
  }

  const statusCode = t < 30 ? 1 : t < 60 ? 2 : 3;
  const flightPhase = t < 30 ? 'Launch' : t < 60 ? 'Coast' : 'Descent';

  return {
    team_id: 690600,
    packet_counter: t & 0xff,
    altitude_agl: altitude,
    rocket_gps_altitude: altitude + 20.0,
    rocket_latitude:  baseLat + latDrift,
    rocket_longitude: baseLon + lonDrift,
    payload_gps_altitude:  altitude + 15.0,
    payload_latitude:  baseLat + latDrift + 0.00001,
    payload_longitude: baseLon + lonDrift + 0.00001,
    stage_gps_altitude:  altitude + 10.0,
    stage_latitude:  baseLat + latDrift - 0.00001,
    stage_longitude: baseLon + lonDrift - 0.00001,
    gyro_x: gyroX, gyro_y: gyroY, gyro_z: gyroZ,
    accel_x: rand(-0.5, 0.5), accel_y: rand(-0.5, 0.5), accel_z: accelZ,
    angle: rand(0, 45),
    status_code: statusCode,
    mission_time: t,
    flight_phase: flightPhase,
  };
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function sendRealTelemetry() {
  console.log('🚀 Real Telemetry Simulator (JS)');
  console.log('='.repeat(50));
  console.log('📡 Sending realistic rocket telemetry data...');
  console.log('🎯 Flight profile:');
  console.log('   - Launch phase  (0–30 s): High acceleration');
  console.log('   - Coast phase  (30–60 s): Apogee');
  console.log('   - Descent phase  (60 s+): Parachute deployment');
  console.log();

  for (let i = 0; i < 120; i++) {
    const telemetry = createRealisticTelemetry(i);

    try {
      const result = await postJson('/api/test_telemetry', telemetry);
      if (result.status === 200) {
        const p = telemetry;
        console.log(
          `📡 Packet ${String(p.packet_counter).padStart(3)}: ` +
          `Alt=${p.altitude_agl.toFixed(1).padStart(6)}m  ` +
          `Phase=${p.flight_phase.padEnd(8)}  ` +
          `Status=${p.status_code}`
        );
      } else {
        console.error(`❌ Failed to send telemetry: HTTP ${result.status}`);
      }
    } catch (err) {
      console.error(`❌ Error: ${err.message}`);
      break;
    }

    await new Promise((r) => setTimeout(r, 1000)); // 1 Hz
  }

  console.log('\n✅ Simulation complete');
}

sendRealTelemetry().catch(console.error);