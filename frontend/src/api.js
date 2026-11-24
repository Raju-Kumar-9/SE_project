const BASE = "/api";

async function handle(res) {
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export function sendChatMessage(sessionId, message, inputMode = "interview", finishInput = false) {
  return fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message, input_mode: inputMode, finish_input: finishInput }),
  }).then(handle);
}

export function fetchRequirements(sessionId) {
  return fetch(`${BASE}/requirements?session_id=${sessionId}`).then(handle);
}

export function recordApproval(requirementId, decision, reviewer, notes, modifiedStatement, modifiedAcceptanceCriteria) {
  return fetch(`${BASE}/approvals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      requirement_id: requirementId,
      decision,
      reviewer,
      notes,
      modified_statement: modifiedStatement,
      modified_acceptance_criteria: modifiedAcceptanceCriteria,
    }),
  }).then(handle);
}

export function refreshFinalDocuments(sessionId, revisions = []) {
  return fetch(`${BASE}/documents/${encodeURIComponent(sessionId)}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revisions }),
  }).then(handle);
}

export function fetchAuditTrail(sessionId) {
  return fetch(`${BASE}/audit?session_id=${encodeURIComponent(sessionId)}`).then(handle);
}
