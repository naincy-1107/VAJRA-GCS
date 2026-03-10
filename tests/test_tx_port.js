#!/usr/bin/env node
/**
 * test_tx_port.js
 * Tests TX serial port functionality by sending test packets.
 * This test sends telemetry packets through the serial port to verify
 * hardware communication with the rocket's transmission system.
 * JS port of Tests/test_tx_port.py
 */

'use strict';

const { SerialPort } = require('serialport');

const TX_PORT = '/dev/ttyACM0';
const BAUD    = 19200;

// ─── Packet builders ──────────────────────────────────────────────────────────

function createTestPacket() {
  const packet = Buffer.alloc(78, 0);
  let off = 0;

  // Header
  packet[off++] = 0xff; packet[off++] = 0xff;
  packet[off++] = 0x54; packet[off++] = 0x52;

  packet[off++] = 142; // Team ID
  packet[off++] = 1;   // Counter

  const values = [
    100.5, 41.015234, 28.979530, 120.3,
    41.015240, 28.979535, 115.7,
    0.5, -0.3, 0.8, 0.1, -0.2, -9.81, 15.5,
    0, 0, 0,
  ];
  for (const v of values) {
    packet.writeFloatLE(v, off);
    off += 4;
  }

  packet[off++] = 2; // Status

  // Checksum (XOR from offset 4 to current-1)
  let cs = 0;
  for (let i = 4; i < off; i++) cs ^= packet[i];
  packet[off++] = cs;

  packet[off++] = 0x0d;
  packet[off]   = 0x0a;

  return packet;
}

function createSimpleTestPacket() {
  const packet = Buffer.alloc(42, 0);
  let off = 0;

  packet[off++] = 0xab; // Header

  const values = [100.5, 1001.25, 0.1, -0.2, -1.0, 0.5, -0.3, 15.5];
  for (const v of values) {
    packet.writeFloatLE(Math.round(v * 100) / 100, off);
    off += 4;
  }

  let cs = 0;
  for (let i = 1; i < off; i++) cs = (cs + packet[i]) & 0xff;
  packet[off++] = cs;

  packet[off++] = 0x0d;
  packet[off]   = 0x0a;

  return packet.slice(0, off + 1);
}

// ─── Port listing ─────────────────────────────────────────────────────────────

async function listAvailablePorts() {
  const ports = await SerialPort.list();
  console.log('🔍 Available serial ports:');
  if (!ports.length) { console.log('   (none found)'); return; }
  for (const p of ports) {
    console.log(`   ${p.path}: ${p.manufacturer ?? p.friendlyName ?? '—'}`);
    if (p.pnpId) console.log(`      HW ID: ${p.pnpId}`);
  }
}

// ─── TX test ─────────────────────────────────────────────────────────────────

function testTxPort() {
  return new Promise((resolve) => {
    console.log(`\n🔌 Testing TX port ${TX_PORT} @ ${BAUD} baud...`);

    const ser = new SerialPort({ path: TX_PORT, baudRate: BAUD, autoOpen: false });

    ser.open((err) => {
      if (err) {
        console.error(`❌ Serial connection failed: ${err.message}`);
        console.log('💡 Make sure:');
        console.log(`   - Device is connected to ${TX_PORT}`);
        console.log('   - You have port access permissions');
        console.log('   - Port is not in use by another process');
        return resolve(false);
      }

      console.log(`✅ Connected to ${TX_PORT}`);

      // Test 1 – simple packet
      const simple = createSimpleTestPacket();
      ser.write(simple, () => {
        const hex = [...simple].map(b => b.toString(16).padStart(2,'0').toUpperCase()).join(' ');
        console.log(`\n📤 Test 1: Sent simple packet (${simple.length} bytes)`);
        console.log(`📦 Packet: ${hex}`);
      });

      setTimeout(() => {
        // Test 2 – full 78-byte packet
        const full = createTestPacket();
        ser.write(full, () => {
          const preview = [...full.slice(0,20)].map(b => b.toString(16).padStart(2,'0').toUpperCase()).join(' ');
          console.log(`\n📤 Test 2: Sent full packet (${full.length} bytes)`);
          console.log(`📦 Packet: ${preview}...`);
        });

        // Test 3 – burst of 5
        let sent = 0;
        const burst = () => {
          if (sent >= 5) {
            ser.close();
            console.log('\n✅ All tests completed!');
            console.log(`📊 Sent packets to ${TX_PORT} @ ${BAUD} baud\n`);
            return resolve(true);
          }
          const p = createTestPacket();
          p[5] = sent + 1; // patch counter
          ser.write(p, () => {
            console.log(`✅ Burst packet ${sent + 1}/5`);
            sent++;
            setTimeout(burst, 100);
          });
        };

        setTimeout(burst, 600);
      }, 500);
    });

    ser.on('error', (err) => { console.error(`❌ Serial error: ${err.message}`); resolve(false); });
  });
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log('🧪 TX Port Test Script (JS)');
  console.log('='.repeat(50));

  await listAvailablePorts();

  const ok = await testTxPort();
  console.log(ok ? '\n🎉 TX port test PASSED!' : '\n💥 TX port test FAILED!');
  process.exit(ok ? 0 : 1);
}

main().catch(console.error);