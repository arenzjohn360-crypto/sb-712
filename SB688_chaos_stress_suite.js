'use strict';

// ═══════════════════════════════════════════════════════════════════════════
//  ♛  SB688 CHAOS STRESS SUITE  ♛
//  Industrial-grade simulation — Aerospace · Defense · Deep-Sea
//  10,000-iteration continuous loop proving self-healing integrity
// ═══════════════════════════════════════════════════════════════════════════
//
//  Scenarios
//  ─────────
//  1. AEROSPACE_PACKET_LOSS   — kill trigger + full comms blackout (0-50 ms),
//                               then autonomous local recovery
//  2. BIT_FLIP_CORRUPTION     — kill + concurrent burst of N additional kills
//                               (simulates radiation-induced state thrash)
//  3. HIGH_FREQ_KILLS         — 5-20 concurrent kill triggers blasted while
//                               system is already in HEALING state
//  4. ZERO_DRIFT_BASELINE     — single kill + single check: nominal path
//
//  Assertion after every scenario: integrity must be exactly GOLDEN (1.0)
//
//  Usage:  node SB688_chaos_stress_suite.js
//  Exit 0 → 100 % recovery, 0 % drift
//  Exit 1 → one or more iterations drifted
//  Exit 2 → unhandled rejection / fatal error
// ═══════════════════════════════════════════════════════════════════════════

const {
  getSystemIntegrity,
  triggerInfrastructureKill,
  checkEngineStatus,
} = require('./SB688_systemIntegrity');

// ── Configuration ────────────────────────────────────────────────────────
const ITERATIONS   = 10_000;
const LOG_INTERVAL = 100;   // print progress every N iterations
const GOLDEN       = 1.0;

// ── Runtime counters ─────────────────────────────────────────────────────
let passed = 0;
let failed = 0;

// ── Utilities ────────────────────────────────────────────────────────────

/** Inclusive random integer in [min, max]. */
function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

/** Non-blocking sleep. */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ═══════════════════════════════════════════════════════════════════════════
//  SCENARIO 1 — Aerospace Packet Loss & Latency
//
//  Models a complete telemetry dropout in a deep-space or high-altitude
//  platform.  After a kill trigger the communication channel is severed
//  for a random blackout window (0–50 ms).  The system must recover
//  autonomously using only local state; no external command arrives during
//  the blackout.  Recovery is invoked only after comms are restored.
// ═══════════════════════════════════════════════════════════════════════════
async function scenarioAerospacePacketLoss() {
  await triggerInfrastructureKill();

  // Simulate communication blackout — autonomous local dormancy window
  const blackoutMs = randInt(0, 50);
  await sleep(blackoutMs);

  const status    = await checkEngineStatus();
  const integrity = await getSystemIntegrity();

  return {
    scenario : 'AEROSPACE_PACKET_LOSS',
    blackoutMs,
    status,
    integrity,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
//  SCENARIO 2 — Industrial Bit-Flip / Memory Corruption
//
//  Models radiation-induced bit-flips that repeatedly thrash the state
//  register while a heal cycle is already in progress.  A primary kill
//  puts the system in HEALING; N additional concurrent kills are enqueued
//  immediately without awaiting (simulating simultaneous register hits).
//  The stateQueue must serialize all mutations; a single checkEngineStatus
//  call issued after all kills must still return the system to GOLDEN.
// ═══════════════════════════════════════════════════════════════════════════
async function scenarioBitFlipCorruption() {
  // Primary kill — enters HEALING
  await triggerInfrastructureKill();

  // Concurrent burst simulating radiation hits — do NOT await individually
  const burstCount = randInt(2, 8);
  const burst = [];
  for (let i = 0; i < burstCount; i++) {
    burst.push(triggerInfrastructureKill());
  }

  // Enqueue recovery BEFORE the burst has settled — the queue guarantees
  // the check executes only after all burst kills complete
  const statusPromise = checkEngineStatus();

  // Let burst settle, then await recovery
  await Promise.all(burst);
  const status    = await statusPromise;
  const integrity = await getSystemIntegrity();

  return {
    scenario   : 'BIT_FLIP_CORRUPTION',
    burstCount,
    status,
    integrity,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
//  SCENARIO 3 — High-Frequency Intermittent Kill Triggers
//
//  Models an electromagnetic pulse or a cascading software fault storm that
//  fires 5–20 kill triggers in rapid succession while the system is already
//  in a HEALING state.  All kills are enqueued concurrently via Promise.all;
//  the stateQueue must not deadlock, freeze, or lose track of state.
//  A single checkEngineStatus issued after all kills drain must restore
//  integrity to exactly GOLDEN.
// ═══════════════════════════════════════════════════════════════════════════
async function scenarioHighFreqKills() {
  const killCount = randInt(5, 20);

  // Fire all kills concurrently — they queue serially inside withStateLock
  const kills = [];
  for (let i = 0; i < killCount; i++) {
    kills.push(triggerInfrastructureKill());
  }
  await Promise.all(kills);

  // Single recovery call must drain the full HEALING chain
  const status    = await checkEngineStatus();
  const integrity = await getSystemIntegrity();

  return {
    scenario  : 'HIGH_FREQ_KILLS',
    killCount,
    status,
    integrity,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
//  SCENARIO 4 — Zero-Drift Baseline
//
//  Nominal single-kill + single-check cycle.  Validates the fundamental
//  recovery contract on every fourth iteration so baseline regression is
//  always measured alongside the stress scenarios.
// ═══════════════════════════════════════════════════════════════════════════
async function scenarioZeroDriftBaseline() {
  await triggerInfrastructureKill();
  const status    = await checkEngineStatus();
  const integrity = await getSystemIntegrity();

  return {
    scenario  : 'ZERO_DRIFT_BASELINE',
    status,
    integrity,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
//  ASSERTION ENGINE
//  Throws on any deviation from GOLDEN.  Validates:
//    · integrity is a finite number (no NaN, undefined, Infinity)
//    · integrity === exactly 1.0
// ═══════════════════════════════════════════════════════════════════════════
function assertGolden(result, iteration) {
  const { integrity, scenario } = result;

  if (integrity === undefined || integrity === null) {
    throw new Error(`Iter ${iteration} [${scenario}] — integrity is ${integrity}`);
  }
  if (typeof integrity !== 'number' || !isFinite(integrity)) {
    throw new Error(`Iter ${iteration} [${scenario}] — integrity is non-finite: ${integrity}`);
  }
  if (integrity !== GOLDEN) {
    throw new Error(
      `Iter ${iteration} [${scenario}] — integrity=${integrity} (expected ${GOLDEN})`
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  TERMINAL LOGGER
//  Overwrites the same line for fluid real-time output.
// ═══════════════════════════════════════════════════════════════════════════
function logProgress(iter, scenarioName) {
  if (iter % LOG_INTERVAL !== 0 && iter !== ITERATIONS) return;

  const pct         = iter / ITERATIONS;
  const barFilled   = Math.floor(pct * 32);
  const bar         = '█'.repeat(barFilled).padEnd(32, '░');
  const driftPct    = failed === 0 ? '0.0000' : ((failed / iter) * 100).toFixed(4);
  const recoveryPct = ((passed / iter) * 100).toFixed(2);

  process.stdout.write(
    `\r  [${bar}] ` +
    `${String(iter).padStart(5)}/${ITERATIONS} ` +
    `| ${scenarioName.padEnd(22)} ` +
    `| ✓ ${String(passed).padStart(5)} Healed ` +
    `| ✗ ${String(failed).padStart(3)} Failures ` +
    `| Recovery: ${recoveryPct}% | Drift: ${driftPct}%   `
  );
}

// ═══════════════════════════════════════════════════════════════════════════
//  MAIN CHAOS LOOP
// ═══════════════════════════════════════════════════════════════════════════
async function runChaosLoop() {
  console.log('\n');
  console.log('  ████████████████████████████████████████████████████████████');
  console.log('  ██                                                        ██');
  console.log('  ██   ♛  SB688  CHAOS  STRESS  SUITE  ·  v1.0  ♛         ██');
  console.log('  ██   Aerospace · Defense · Deep-Sea · 10,000 iterations  ██');
  console.log('  ██                                                        ██');
  console.log('  ████████████████████████████████████████████████████████████');
  console.log('\n  Scenarios: AEROSPACE_PACKET_LOSS · BIT_FLIP_CORRUPTION');
  console.log('             HIGH_FREQ_KILLS · ZERO_DRIFT_BASELINE');
  console.log(`\n  Target: ${ITERATIONS.toLocaleString()} iterations · 0% drift · 100% autonomous recovery\n`);

  const scenarios = [
    scenarioAerospacePacketLoss,
    scenarioBitFlipCorruption,
    scenarioHighFreqKills,
    scenarioZeroDriftBaseline,
  ];

  const startTime = Date.now();
  let lastScenario = '';

  for (let i = 1; i <= ITERATIONS; i++) {
    const fn = scenarios[(i - 1) % scenarios.length];
    let result;

    try {
      result       = await fn();
      lastScenario = result.scenario;
      assertGolden(result, i);
      passed++;
    } catch (err) {
      failed++;
      lastScenario = result ? result.scenario : 'UNKNOWN';
      // Print failure on a new line so it is not overwritten
      process.stdout.write('\n');
      console.error(`  [DRIFT DETECTED] Iteration ${i}: ${err.message}`);
    }

    logProgress(i, lastScenario);
  }

  const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(2);
  const recoveryRate = ((passed / ITERATIONS) * 100).toFixed(4);
  const driftRate    = ((failed / ITERATIONS) * 100).toFixed(4);

  console.log('\n\n  ────────────────────────────────────────────────────────────');
  console.log('  ♛  FINAL REPORT — SB688 CHAOS STRESS SUITE');
  console.log('  ────────────────────────────────────────────────────────────');
  console.log(`  Total Iterations     : ${ITERATIONS.toLocaleString()}`);
  console.log(`  Autonomous Heals     : ${passed.toLocaleString()}`);
  console.log(`  Failures / Drift     : ${failed.toLocaleString()}`);
  console.log(`  Recovery Rate        : ${recoveryRate}%`);
  console.log(`  System Drift         : ${driftRate}%`);
  console.log(`  Elapsed Time         : ${elapsedSec}s`);
  console.log('  ────────────────────────────────────────────────────────────');

  if (failed === 0) {
    console.log('  ✅  TARGET MET — 100.0000% recovery · 0.0000% system drift.');
    console.log('      Golden Directive integrity confirmed across all scenarios.');
  } else {
    console.log(`  ⚠️   DRIFT DETECTED — ${failed} iteration(s) did not fully recover.`);
    console.log('      Review [DRIFT DETECTED] lines above for root cause.');
  }

  console.log('  ████████████████████████████████████████████████████████████\n');

  process.exit(failed > 0 ? 1 : 0);
}

// ── Global safety net — must be zero in a healthy run ────────────────────
process.on('unhandledRejection', (reason) => {
  process.stdout.write('\n');
  console.error('  [UNHANDLED REJECTION]', reason);
  process.exit(2);
});

runChaosLoop().catch((err) => {
  process.stdout.write('\n');
  console.error('  [FATAL]', err);
  process.exit(2);
});
