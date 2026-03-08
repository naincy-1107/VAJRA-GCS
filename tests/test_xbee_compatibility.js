#!/usr/bin/env node
/**
 * test_xbee_compatibility.js
 * Verifies XBee packet format with all-zero float values.
 * JS port of Tests/test_xbee_compatibility.py
 */

'use strict';

function createXbeePacket(counter) {
  const packet = Buffer.alloc(78, 0);
  let offset = 0;

  // Header FF FF 54 52
  packet[offset++] = 0xff;
  packet[offset++] = 0xff;
  packet[offset++] = 0x54;
  packet[offset++] = 0x52;

  packet[offset++] = 142;          // Team ID
  packet[offset++] = counter & 0xff;

  // 17 floats all = 0.0
  for (let i = 0; i < 17; i++) {
    packet.writeFloatLE(0.0, offset);
    offset += 4;
  }

  // Status = 0
  packet[offset++] = 0;

  // Checksum
  let sum = 0;
  for (let i = 4; i < 75; i++) sum += packet[i];
  packet[offset++] = sum & 0xff;

  // Footer
  packet[offset++] = 0x0d;
  packet[offset]   = 0x0a;

  return packet;
}

function testXbeePacket() {
  console.log('🧪 Testing XBee Packet Format');
  console.log('='.repeat(40));

  const packet = createXbeePacket(1);
  let allPassed = true;

  console.log(`📦 Packet length: ${packet.length} bytes`);
  console.log(`🔍 Header: [${[...packet.slice(0,4)].map(b=>'0x'+b.toString(16).padStart(2,'0')).join(', ')}]`);
  console.log(`🏷️  Team ID: ${packet[4]}`);
  console.log(`🔢 Counter: ${packet[5]}`);
  console.log(`📊 Status: ${packet[74]}`);
  console.log(`🔢 Checksum: 0x${packet[75].toString(16).toUpperCase().padStart(2,'0')}`);
  console.log(`📄 Footer: [0x${packet[76].toString(16).toUpperCase()}, 0x${packet[77].toString(16).toUpperCase()}]`);

  // Verify all floats = 0
  let allZeros = true;
  const floatStart = 6;
  for (let i = 0; i < 17; i++) {
    const val = packet.readFloatLE(floatStart + i * 4);
    if (val !== 0.0) { allZeros = false; console.error(`❌ Float ${i}: ${val} (expected 0)`); }
  }
  if (allZeros) console.log('✅ All float values are 0 (XBee compatible)');
  else { allPassed = false; }

  // Verify checksum
  let calcSum = 0;
  for (let i = 4; i < 75; i++) calcSum += packet[i];
  calcSum &= 0xff;
  if (calcSum === packet[75]) console.log('✅ Checksum is correct');
  else {
    console.error(`❌ Checksum mismatch: calc=0x${calcSum.toString(16).toUpperCase()}, stored=0x${packet[75].toString(16).toUpperCase()}`);
    allPassed = false;
  }

  console.log(`\n🎯 XBee compatibility test ${allPassed ? 'PASSED' : 'FAILED'}!\n`);
  return allPassed && allZeros;
}

const ok = testXbeePacket();
process.exit(ok ? 0 : 1);