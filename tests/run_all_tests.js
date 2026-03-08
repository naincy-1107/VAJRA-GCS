#!/usr/bin/env node
/**
 * run_all_tests.js
 * Runs all unit/integration tests that do NOT require physical hardware.
 * Hardware-dependent tests (test_tx_port, tx_port_simulator) are skipped.
 */

'use strict';

const { execFileSync } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

const TESTS = [
  { name: 'TX Packet Format',       file: 'Tests/test_tx_format.js',         hardware: false },
  { name: 'XBee Compatibility',     file: 'Tests/test_xbee_compatibility.js', hardware: false },
  { name: 'Socket.IO Connection',   file: 'Tests/test_socket_connection.js',  hardware: false, needsServer: true },
  // Hardware-only – skipped in CI
  { name: 'TX Port (hardware)',      file: 'Tests/test_tx_port.js',            hardware: true },
  { name: 'TX Port Simulator',      file: 'Tests/tx_port_simulator.js',        hardware: true },
];

let passed = 0, failed = 0, skipped = 0;

function runTest(file) {
  execFileSync(process.execPath, [path.join(ROOT, file)], {
    stdio: 'inherit',
    cwd: ROOT,
    timeout: 15000,
  });
}

console.log('🧪 TEKNOFEST GCS – Test Suite (Node.js)');
console.log('='.repeat(50));
console.log();

for (const test of TESTS) {
  if (test.hardware) {
    console.log(`⏭️  SKIP  ${test.name} (requires physical hardware)\n`);
    skipped++;
    continue;
  }

  if (test.needsServer) {
    // Quick check: is the backend reachable?
    try {
      require('http').get('http://127.0.0.1:5000/api/ports', () => {});
    } catch (_) {
      console.log(`⏭️  SKIP  ${test.name} (backend not running)\n`);
      skipped++;
      continue;
    }
  }

  process.stdout.write(`▶  Running: ${test.name} ... `);
  try {
    runTest(test.file);
    console.log('✅ PASSED\n');
    passed++;
  } catch (err) {
    console.log('❌ FAILED\n');
    failed++;
  }
}

console.log('='.repeat(50));
console.log(`Results:  ✅ ${passed} passed  |  ❌ ${failed} failed  |  ⏭️  ${skipped} skipped`);
console.log();

process.exit(failed > 0 ? 1 : 0);