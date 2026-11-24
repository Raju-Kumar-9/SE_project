import { useEffect, useState } from "react";
import { fetchAuditTrail } from "../api.js";

export default function AuditTrail({ sessionId }) {
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    if (!sessionId) return undefined;
    fetchAuditTrail(sessionId)
      .then((result) => { if (active) setEvents(result.events ?? []); })
      .catch((err) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [sessionId]);

  if (!sessionId) return <p>Start an interview to create an audit trail.</p>;
  if (error) return <p role="alert">Could not load audit trail: {error}</p>;

  return (
    <section className="review-card">
      <h2>Session Audit Trail</h2>
      <p>Interview messages, agent events, and reviewer decisions in time order.</p>
      {events.length === 0 ? <p>No audit events recorded yet.</p> : (
        <ol className="audit-list">{events.map((item, index) => (
          <li key={`${item.created_at}-${index}`}>
            <time>{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</time>
            <strong>{item.actor} · {item.event}</strong>
            <span className="audit-kind">{item.kind}</span>
            <details><summary>Details</summary><pre>{JSON.stringify(item.details, null, 2)}</pre></details>
          </li>
        ))}</ol>
      )}
    </section>
  );
}
