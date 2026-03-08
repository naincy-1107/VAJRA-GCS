#!/usr/bin/env node
/**
 * test_socket_connection.js
 * Tests Socket.IO connection + HTTP endpoints.
 * JS port of Tests/test_socket_connection.py
 */

'use strict';

const http  = require('http');
const { io: ioClient } = require('socket.io-client');

// ─── HTTP helpers ─────────────────────────────────────────────────────────────

function httpGet(path) {
  return new Promise((resolve, reject) => {
    http.get({ hostname: '127.0.0.1', port: 5000, path }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    }).on('error', reject);
  });
}

function httpPost(path, body = {}) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      { hostname: '127.0.0.1', port: 5000, path, method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } },
      (res) => {
        let buf = '';
        res.on('data', (c) => (buf += c));
        res.on('end', () => {
          try { resolve({ status: res.statusCode, body: JSON.parse(buf) }); }
          catch { resolve({ status: res.statusCode, body: buf }); }
        });
      }
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

// ─── HTTP endpoint tests ──────────────────────────────────────────────────────

async function testHttpEndpoints() {
  console.log('\n🌐 Testing HTTP endpoints...\n');

  try {
    const res = await httpGet('/api/ports');
    if (res.status === 200) console.log(`✅ GET /api/ports: ${JSON.stringify(res.body).slice(0, 80)}...`);
    else console.error(`❌ GET /api/ports: HTTP ${res.status}`);
  } catch (e) { console.error(`❌ GET /api/ports: ${e.message}`); }

  try {
    const res = await httpPost('/api/test_telemetry', {});
    if (res.status === 200) console.log(`✅ POST /api/test_telemetry: ${JSON.stringify(res.body).slice(0, 80)}...`);
    else console.error(`❌ POST /api/test_telemetry: HTTP ${res.status}`);
  } catch (e) { console.error(`❌ POST /api/test_telemetry: ${e.message}`); }

  try {
    const res = await httpGet('/api/ports/status');
    if (res.status === 200) console.log(`✅ GET /api/ports/status: ${JSON.stringify(res.body).slice(0, 80)}...`);
    else console.error(`❌ GET /api/ports/status: HTTP ${res.status}`);
  } catch (e) { console.error(`❌ GET /api/ports/status: ${e.message}`); }
}

// ─── Socket.IO test ───────────────────────────────────────────────────────────

function testSocketConnection() {
  return new Promise((resolve) => {
    console.log('\n🔌 Testing Socket.IO connection...\n');
    const socket = ioClient('http://127.0.0.1:5000', {
      transports: ['websocket', 'polling'],
      reconnection: false,
      timeout: 5000,
    });

    const timer = setTimeout(() => {
      console.error('❌ Socket.IO connection timed out');
      socket.disconnect();
      resolve(false);
    }, 8000);

    socket.on('connect', async () => {
      console.log(`✅ Socket.IO connected – ID: ${socket.id}`);
      socket.emit('telemetry_request');
      console.log('📤 Sent telemetry_request');

      // Send test telemetry via HTTP to trigger a broadcast
      try {
        const res = await httpPost('/api/test_telemetry', {});
        console.log(`✅ Test telemetry injected via HTTP: ${JSON.stringify(res.body).slice(0, 60)}...`);
      } catch (e) { console.error(`❌ HTTP test_telemetry: ${e.message}`); }
    });

    socket.on('telemetry', (data) => {
      console.log('📡 Received telemetry event:');
      console.log(`   Team ID:        ${data.team_id}`);
      console.log(`   Packet counter: ${data.packet_counter}`);
      console.log(`   Altitude:       ${data.altitude_agl}m`);
      console.log(`   Status:         ${data.status}`);
      console.log(`   Keys: [${Object.keys(data).join(', ')}]`);
      clearTimeout(timer);
      socket.disconnect();
      resolve(true);
    });

    socket.on('disconnect', (reason) => console.log(`🔌 Disconnected: ${reason}`));
    socket.on('connect_error', (err) => { console.error(`❌ connect_error: ${err.message}`); clearTimeout(timer); socket.disconnect(); resolve(false); });
  });
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log('🚀 Socket.IO Connection Test (JS)');
  console.log('='.repeat(50));

  await testHttpEndpoints();
  const socketOk = await testSocketConnection();

  console.log(`\n${socketOk ? '✅' : '❌'} Test completed!\n`);
  process.exit(socketOk ? 0 : 1);
}

main().catch(console.error);