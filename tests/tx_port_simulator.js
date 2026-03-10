#!/usr/bin/env node
/**
 * tx_port_simulator.js
 * Listens on a serial port for 78-byte packets and prints them.
 * This simulator acts as a receiver for telemetry packets, useful for
 * testing the transmission without actual rocket hardware.
 * JS port of Tests/tx_port_simulator.py
 *
 * Usage:  node Tests/tx_port_simulator.js <port> [duration_seconds]
 *   e.g.: node Tests/tx_port_simulator.js /dev/ttyACM1 10
 */

'use strict';

const { SerialPort } = require('serialport');

const [,, port, durStr] = process.argv;
const duration = parseInt(durStr ?? '10', 10) * 1000; // ms

// ─── Packet parser ────────────────────────────────────────────────────────────

function parse78BytePacket(buf) {
  if (!Buffer.isBuffer(buf) || buf.length !== 78) return null;
  const data = {};
  data.header = [...buf.slice(0, 4)].map(b => '0x' + b.toString(16).padStart(2,'0').toUpperCase());
  data.team_id = buf[4];
  data.packet_counter = buf[5];

  const names = [
    'altitude_agl','rocket_gps_altitude','rocket_latitude','rocket_longitude',
    'payload_gps_altitude','payload_latitude','payload_longitude',
    'stage_gps_altitude','stage_latitude','stage_longitude',
    'gyro_x','gyro_y','gyro_z','accel_x','accel_y','accel_z','angle',
  ];
  let off = 6;
  for (const n of names) { data[n] = buf.readFloatLE(off); off += 4; }
  data.status_code = buf[74];
  data.checksum    = buf[75];
  data.footer = [buf[76], buf[77]];
  return data;
}

// ─── Port listing ─────────────────────────────────────────────────────────────

async function listPorts() {
  const ports = await SerialPort.list();
  console.log('🔍 Available serial ports:');
  ports.forEach(p => console.log(`   ${p.path}: ${p.manufacturer ?? '—'}`));
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  if (!port) {
    console.log('Usage: node Tests/tx_port_simulator.js <port> [duration]');
    console.log('Example: node Tests/tx_port_simulator.js /dev/ttyACM1 10');
    await listPorts();
    process.exit(1);
  }

  console.log('📡 TX Port Receiver Simulator (JS)');
  console.log(`🎯 Listening on: ${port}`);
  console.log(`⏱️  Duration: ${duration / 1000}s`);
  console.log('='.repeat(50));

  const ser = new SerialPort({ path: port, baudRate: 19200, autoOpen: false });
  let packetBuffer = Buffer.alloc(0);
  let packetCount = 0;

  ser.open((err) => {
    if (err) { console.error(`❌ Cannot open ${port}: ${err.message}`); process.exit(1); }
    console.log(`✅ Connected to ${port} @ 19200 baud\n`);
  });

  ser.on('data', (chunk) => {
    const hex = [...chunk.slice(0,20)].map(b=>b.toString(16).padStart(2,'0').toUpperCase()).join(' ');
    console.log(`[RAW] ${port}: ${chunk.length} bytes – ${hex}${chunk.length > 20 ? '...' : ''}`);
    packetBuffer = Buffer.concat([packetBuffer, chunk]);

    while (packetBuffer.length >= 78) {
      let startIdx = -1;
      for (let i = 0; i < packetBuffer.length - 1; i++) {
        if (packetBuffer[i] === 0xff && packetBuffer[i+1] === 0xff) { startIdx = i; break; }
      }
      if (startIdx === -1) { packetBuffer = Buffer.alloc(0); break; }
      if (packetBuffer.length < startIdx + 78) break;

      const pkt = packetBuffer.slice(startIdx, startIdx + 78);
      const d = parse78BytePacket(pkt);
      if (d) {
        packetCount++;
        console.log(`📦 Packet ${packetCount}:`);
        console.log(`   Team ID: ${d.team_id}`);
        console.log(`   Counter: ${d.packet_counter}`);
        console.log(`   Altitude: ${d.altitude_agl.toFixed(1)}m`);
        console.log(`   GPS: Lat=${d.rocket_latitude.toFixed(6)}, Lon=${d.rocket_longitude.toFixed(6)}`);
        console.log(`   IMU: AccZ=${d.accel_z.toFixed(2)}g, GyroZ=${d.gyro_z.toFixed(2)}°/s`);
        console.log(`   Angle: ${d.angle.toFixed(1)}°`);
        console.log(`   Status: ${d.status_code}  Checksum: 0x${d.checksum.toString(16).toUpperCase().padStart(2,'0')}\n`);
      }
      packetBuffer = packetBuffer.slice(startIdx + 78);
    }
  });

  ser.on('error', (err) => console.error(`❌ Serial error: ${err.message}`));

  // Stop after <duration> ms
  setTimeout(() => {
    const elapsed = duration / 1000;
    console.log('\n📊 Summary:');
    console.log(`   Received: ${packetCount} packets`);
    console.log(`   Duration: ${elapsed}s`);
    console.log(`   Rate:     ${(packetCount / elapsed).toFixed(1)} packets/s`);
    ser.close(() => { console.log('✅ TX receiver simulation complete\n'); process.exit(0); });
  }, duration);
}

main().catch(console.error);