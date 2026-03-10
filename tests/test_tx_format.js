#!/usr/bin/env node
/**
 * test_tx_format.js
 * Verifies that the JS createTxPacket() output is byte-identical
 * to the reference txCheck.py format.
 * This test ensures the telemetry packet creation function produces
 * the correct binary format for transmission.
 * JS port of Tests/test_tx_format.py
 */

'use strict';

// Import the backend module to reuse createTxPacket
const { createTxPacket } = require('../gcs_backend.js');

// ─── Reference Implementation (mirrors txCheck.py) ───────────────────────────

function floatToBytes(value) {
  const buf = Buffer.alloc(4);
  buf.writeFloatLE(value, 0);
  return buf;
}

function calculateChecksumTxCheck(packet) {
  let sum = 0;
  for (let i = 4; i < 75; i++) sum += packet[i];
  return sum & 0xff;
}

function generateTxCheckPacket(counter) {
  const packet = Buffer.alloc(78, 0);
  let offset = 0;

  // Header FF FF 54 52
  packet[offset++] = 0xff;
  packet[offset++] = 0xff;
  packet[offset++] = 0x54;
  packet[offset++] = 0x52;

  // Team ID = 142, counter
  packet[offset++] = 142;
  packet[offset++] = counter & 0xff;

  // 17 floats (matching test_tx_format.py test data)
  const floatFields = [
    1238.1, 1240.1, 41.015236, 28.979540,
    115.7,  41.015240, 28.979535,
    110.2,  41.015230, 28.979525,
    0.26,  -0.11,  0.61,
   -0.09,   0.10, -0.90,
    15.8,
  ];
  for (const f of floatFields) {
    const fb = floatToBytes(f);
    fb.copy(packet, offset);
    offset += 4;
  }

  // Status = 4
  packet[offset++] = 4;

  // Checksum
  packet[offset++] = calculateChecksumTxCheck(packet);

  // Footer
  packet[offset++] = 0x0d;
  packet[offset]   = 0x0a;

  return packet;
}

// ─── Test ─────────────────────────────────────────────────────────────────────

function testPacketFormats() {
  console.log('🧪 Testing TX packet format compatibility...\n');

  const testData = {
    team_id: 142, packet_counter: 4,
    altitude_agl:         1238.1,
    rocket_gps_altitude:  1240.1,
    rocket_latitude:      41.015236,
    rocket_longitude:     28.979540,
    payload_gps_altitude: 115.7,
    payload_latitude:     41.015240,
    payload_longitude:    28.979535,
    stage_gps_altitude:   110.2,
    stage_latitude:       41.015230,
    stage_longitude:      28.979525,
    gyro_x:   0.26,  gyro_y: -0.11, gyro_z:  0.61,
    accel_x: -0.09, accel_y:  0.10, accel_z: -0.90,
    angle: 15.8,
    status_code: 4,
  };

  const packetJs     = createTxPacket(testData);
  const packetRef    = generateTxCheckPacket(4);

  console.log('📦 Packet lengths:');
  console.log(`   JS Reference:  ${packetJs.length} bytes`);
  console.log(`   txCheck ref:   ${packetRef.length} bytes`);

  console.log('\n🔍 Header:');
  console.log(`   JS Ref:  [${[...packetJs.slice(0,4)].map(b=>'0x'+b.toString(16).padStart(2,'0')).join(', ')}]`);
  console.log(`   txCheck: [${[...packetRef.slice(0,4)].map(b=>'0x'+b.toString(16).padStart(2,'0')).join(', ')}]`);

  console.log('\n🏷️  Team ID & Counter:');
  console.log(`   JS Ref:  Team=${packetJs[4]}, Counter=${packetJs[5]}`);
  console.log(`   txCheck: Team=${packetRef[4]}, Counter=${packetRef[5]}`);

  console.log('\n🔢 Checksum:');
  console.log(`   JS Ref:  0x${packetJs[75].toString(16).toUpperCase().padStart(2,'0')}`);
  console.log(`   txCheck: 0x${packetRef[75].toString(16).toUpperCase().padStart(2,'0')}`);

  console.log('\n📄 Footer:');
  console.log(`   JS Ref:  [0x${packetJs[76].toString(16).toUpperCase()}, 0x${packetJs[77].toString(16).toUpperCase()}]`);
  console.log(`   txCheck: [0x${packetRef[76].toString(16).toUpperCase()}, 0x${packetRef[77].toString(16).toUpperCase()}]`);

  let allMatch = true;
  for (let i = 0; i < 78; i++) {
    if (packetJs[i] !== packetRef[i]) {
      console.error(`\n❌ DIFFERENCE at byte ${i}: JS=0x${packetJs[i].toString(16).padStart(2,'0')}, txCheck=0x${packetRef[i].toString(16).padStart(2,'0')}`);
      allMatch = false;
    }
  }

  if (allMatch) {
    console.log('\n✅ SUCCESS: Packets are byte-identical!\n');
    return true;
  } else {
    console.error('\n❌ FAILURE: Packets differ – see above.\n');
    return false;
  }
}

const ok = testPacketFormats();
process.exit(ok ? 0 : 1);