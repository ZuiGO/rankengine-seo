
with open("frontend/app.js", "a") as f:
    f.write("""
// --- Sandbox Approvals ---

async function loadSandboxApprovals() {
  const container = document.getElementById("sandbox-approvals-queue");
  container.innerHTML = '<div class="skeleton-shimmer-row" style="height:100px"></div>'.repeat(3);
  try {
    const res = await fetch("/api/sandbox/suggestions");
    if (!res.ok) throw new Error("Failed to fetch suggestions");
    const data = await res.json();
    renderSandboxApprovals(data.suggestions);
  } catch (err) {
    container.innerHTML = `<div class="service-error">Error loading approvals: ${escapeHtml(err.message)}</div>`;
  }
}

function computeDiffHTML(oldText, newText) {
  if (oldText === newText) return escapeHtml(newText);
  return `
    <div style="margin-bottom:8px;"><span class="diff-del" style="background:#ffcdd2;color:#b71c1c;text-decoration:line-through;padding:2px 4px;border-radius:4px;">${escapeHtml(oldText || "(empty)")}</span></div>
    <div><span class="diff-add" style="background:#c8e6c9;color:#1b5e20;padding:2px 4px;border-radius:4px;">${escapeHtml(newText || "(empty)")}</span></div>
  `;
}

function renderSandboxApprovals(suggestions) {
  const container = document.getElementById("sandbox-approvals-queue");
  container.innerHTML = "";

  if (!suggestions || suggestions.length === 0) {
    container.innerHTML = `<div class="empty-state">No pending suggestions for the sandbox.</div>`;
    return;
  }

  const groups = {};
  suggestions.forEach(s => {
    if (!groups[s.field_type]) groups[s.field_type] = [];
    groups[s.field_type].push(s);
  });

  const lowRiskFields = ["alt_text", "canonical", "footer_copyright"];

  for (const [fieldType, items] of Object.entries(groups)) {
    const groupDiv = document.createElement("div");
    groupDiv.className = "approval-group card";
    groupDiv.style.padding = "20px";
    groupDiv.style.background = "var(--bg-surface)";
    groupDiv.style.borderRadius = "8px";
    groupDiv.style.border = "1px solid var(--border)";
    groupDiv.style.marginBottom = "16px";

    const isLowRisk = lowRiskFields.includes(fieldType);
    
    let html = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; border-bottom:1px solid var(--border); padding-bottom:12px;">
        <h3 style="margin:0; font-size:16px; text-transform:capitalize;">${escapeHtml(fieldType.replace('_', ' '))}</h3>
        ${isLowRisk ? `<button class="btn-primary" onclick="batchApproveSandboxSuggestions('${escapeHtml(fieldType)}')">Batch Approve</button>` : `<span class="badge" style="background:var(--bg-elevated); color:var(--text-secondary)">Individual Approval Required</span>`}
      </div>
      <div class="approval-items">
    `;

    items.forEach(item => {
      html += `
        <div class="approval-item" id="suggestion-${item.id}" style="padding:16px; border:1px solid var(--border); border-radius:6px; margin-bottom:12px; background:var(--bg-base);">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
            <div class="diff-view" style="font-family:var(--font-mono); font-size:13px; line-height:1.5;">
              ${computeDiffHTML(item.current_value, item.suggested_value)}
            </div>
            <div class="status-badge">
              <span class="status-pill status-unchecked">pending</span>
            </div>
          </div>
          
          <div class="context-box" style="background:var(--bg-elevated); padding:12px; border-radius:6px; font-size:13px; margin-bottom:16px;">
            <div style="margin-bottom:8px"><strong>Rationale:</strong> ${escapeHtml(item.rationale)}</div>
            <div><strong>Evidence Source:</strong> <code style="background:var(--bg-base); padding:2px 4px; border-radius:4px;">${escapeHtml(item.evidence_source)}</code></div>
          </div>
          
          <div class="actions" style="display:flex; gap:8px;">
            <button class="btn-primary" onclick="approveSandboxSuggestion('${item.id}')">✓ Approve</button>
            <button class="btn-secondary" onclick="editSandboxSuggestion('${item.id}')">✎ Edit</button>
            <button class="btn-danger" style="background:var(--status-broken); color:white; border:none; border-radius:4px; padding:6px 12px; cursor:pointer;" onclick="rejectSandboxSuggestion('${item.id}')">✕ Reject</button>
          </div>
        </div>
      `;
    });

    html += `</div>`;
    groupDiv.innerHTML = html;
    container.appendChild(groupDiv);
  }
}

async function approveSandboxSuggestion(id) {
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/approve`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to approve");
    showToast("Suggestion approved");
    updateSuggestionStatusUI(id, "approved, pending apply", "status-ok");
  } catch (err) {
    showToast(err.message, true);
  }
}

async function rejectSandboxSuggestion(id) {
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/reject`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to reject");
    showToast("Suggestion rejected");
    updateSuggestionStatusUI(id, "rejected", "status-broken");
  } catch (err) {
    showToast(err.message, true);
  }
}

async function editSandboxSuggestion(id) {
  const newVal = prompt("Edit the suggested value:");
  if (newVal === null) return;
  try {
    const res = await fetch(`/api/sandbox/suggestions/${id}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suggested_value: newVal })
    });
    if (!res.ok) throw new Error("Failed to edit");
    showToast("Suggestion edited and approved");
    loadSandboxApprovals();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function batchApproveSandboxSuggestions(fieldType) {
  try {
    const res = await fetch(`/api/sandbox/suggestions/batch_approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field_type: fieldType })
    });
    if (!res.ok) throw new Error("Failed to batch approve");
    const data = await res.json();
    showToast(`Batch approved ${data.count} items`);
    loadSandboxApprovals();
  } catch (err) {
    showToast(err.message, true);
  }
}

function updateSuggestionStatusUI(id, text, colorClass) {
  const el = document.getElementById(`suggestion-${id}`);
  if (!el) return;
  const badge = el.querySelector(".status-pill");
  if (badge) {
    badge.className = `status-pill ${colorClass}`;
    badge.textContent = text;
  }
  const actions = el.querySelector(".actions");
  if (actions) {
    actions.style.display = "none";
  }
}
""")
