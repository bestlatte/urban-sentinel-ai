/**
 * Fetch API 封裝：四個 REST 端點。
 * 不用 axios（00-tech-stack.md 禁用），用原生 Fetch。
 */

async function fetchDashboard() {
  const resp = await fetch("/api/dashboard");
  return resp.json();
}

async function fetchEvaluateIncident(eventId) {
  const resp = await fetch("/api/incidents/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: eventId }),
  });
  return resp.json();
}

async function fetchWhatIf(content, sessionId, correlationId, currentTraceId) {
  const resp = await fetch("/api/what-if", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId || ChatState.sessionId,
      content: content,
      correlation_id: correlationId || generateId(),
      current_trace_id: currentTraceId || null,
    }),
  });
  return resp.json();
}

async function fetchHealth() {
  const resp = await fetch("/api/health");
  return resp.json();
}
