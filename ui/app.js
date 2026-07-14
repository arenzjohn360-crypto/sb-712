/**
 * app.js — SB-712 IronBraid Control Room
 *
 * Placeholder JavaScript for the control-room UI.
 * Loads proof report JSON files from reports/daily/proof/ when served
 * by a local HTTP server, and updates the dashboard panels.
 *
 * NOTE: This is a static scaffold.  In production, replace the
 * fetchReports() stub with a real API call to a backend service.
 */

"use strict";

// ── Clock ──────────────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById("clock");
  if (el) {
    el.textContent = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";
  }
}
setInterval(updateClock, 1000);
updateClock();

// ── Ledger status (stub) ───────────────────────────────────────────────────
function updateLedgerPanel(data) {
  setText("ledger-chain-state", data.chain_state || "UNKNOWN");
  setText("ledger-seq", data.sequence ?? "—");
  setText("ledger-mirror", data.mirror_agreement ? "AGREED" : "DIVERGED");
  setText("ledger-head-hash", data.current_hash || "—");
}

// ── Quarantine panel (stub) ────────────────────────────────────────────────
function updateQuarantinePanel(items) {
  setText("quarantine-count", items.length);
  setText("quarantine-pending", items.filter((i) => i.status === "PENDING").length);
  const list = document.getElementById("quarantine-list");
  if (!list) return;
  if (items.length === 0) {
    list.innerHTML = '<li class="placeholder">No quarantined items.</li>';
    return;
  }
  list.innerHTML = items
    .map((i) => `<li>${escapeHtml(i.id || "unknown")} — ${escapeHtml(i.reason || "")}</li>`)
    .join("");
}

// ── Checkpoint health (stub) ───────────────────────────────────────────────
function updateCheckpointPanel(state) {
  const nodes = ["phoenix-a", "phoenix-b", "phoenix-c", "ghost"];
  nodes.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const stateEl = el.querySelector(".node-state");
    if (!stateEl) return;
    const nodeState = (state[id] || "DORMANT").toLowerCase();
    stateEl.className = `node-state ${nodeState}`;
    stateEl.textContent = (state[id] || "DORMANT").toUpperCase();
  });
  setText("last-checkpoint", state.last_certified || "—");
  setText("checkpoint-count", state.certified_count ?? 0);
}

// ── Proof report table ─────────────────────────────────────────────────────
function updateProofTable(reports) {
  const tbody = document.getElementById("proof-table-body");
  const countEl = document.getElementById("report-count");
  if (!tbody) return;
  if (!reports || reports.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="6" class="placeholder">No proof reports yet. Run the entrypoint to generate one.</td></tr>';
    if (countEl) countEl.textContent = "0";
    return;
  }
  if (countEl) countEl.textContent = reports.length;
  tbody.innerHTML = reports
    .slice()
    .reverse()
    .map(
      (r) => `
      <tr>
        <td>${escapeHtml(r.timestamp || "—")}</td>
        <td>${escapeHtml(r.run_id || "—")}</td>
        <td>${r.files_scanned ?? "—"}</td>
        <td>${r.mutations_detected ?? "—"}</td>
        <td>${escapeHtml(r.risk_level || "—")}</td>
        <td>${escapeHtml(r.status || "—")}</td>
      </tr>`
    )
    .join("");
}

// ── Fetch & refresh (stub — replace with real API) ─────────────────────────
async function refreshReports() {
  // In a served environment this would call: GET /api/reports or fetch a JSON index.
  // For local file:// usage we populate with placeholder data.
  const placeholder = [
    {
      timestamp: new Date().toISOString(),
      run_id: "scaffold-demo",
      files_scanned: 0,
      mutations_detected: 0,
      risk_level: "LOW",
      status: "PROOF_COMPLETE",
    },
  ];
  updateProofTable(placeholder);
}

// ── Initialise dashboard ───────────────────────────────────────────────────
function initDashboard() {
  // Populate with safe defaults on load.
  updateLedgerPanel({ chain_state: "INTACT", sequence: 0, mirror_agreement: true,
                      current_hash: "genesis" });
  updateQuarantinePanel([]);
  updateCheckpointPanel({ "phoenix-a": "DORMANT", "phoenix-b": "DORMANT",
                          "phoenix-c": "DORMANT", ghost: "DORMANT",
                          last_certified: "—", certified_count: 0 });
  updateProofTable([]);
}

// ── Helpers ────────────────────────────────────────────────────────────────
function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(value);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Boot ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", initDashboard);
