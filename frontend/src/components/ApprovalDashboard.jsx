import { useEffect, useState } from "react";
import { fetchRequirements } from "../api.js";

export default function ApprovalDashboard({ sessionId, pipelineResult }) {
  const [requirements, setRequirements] = useState(pipelineResult?.requirements ?? []);

  useEffect(() => {
    setRequirements(pipelineResult?.requirements ?? []);
    if (sessionId && pipelineResult?.analysis_complete !== false) {
      fetchRequirements(sessionId)
        .then((result) => setRequirements(result.requirements ?? []))
        .catch(() => {});
    }
  }, [pipelineResult, sessionId]);

  if (!pipelineResult) return <p>Finish the client description or interview to see the analysis results.</p>;

  const recommendation = pipelineResult.sdlc_recommendation;
  const documents = pipelineResult.generated_documents ?? [];

  return (
    <div>
      <section className="review-card">
        <h2>Analysis Results</h2>
        <p>These are extracted requirements for the product described by the client. They are analysis results, not a commitment to implement the product.</p>
      </section>

      {recommendation && (
        <section className="review-card">
          <h2>SDLC Recommendation</h2>
          <p>Factor coverage: {recommendation.factor_coverage?.available ?? 0}/{recommendation.factor_coverage?.total ?? 9}</p>
          <ol>
            {(recommendation.ranked_scores ?? []).map((item) => (
              <li key={item.model}>{item.model}: {item.score_percent ?? Math.round(item.score * 100)}%</li>
            ))}
          </ol>
          <p>{recommendation.narration}</p>
          {recommendation.agent_analysis && (
            <div className="sdlc-agent-analysis">
              <h3>SDLC analysis</h3>
              <p>{recommendation.agent_analysis.summary}</p>
              {(recommendation.agent_analysis.per_method ?? []).map((item) => (
                <div key={item.method}>
                  <strong>{item.method}</strong>
                  <p>{item.explanation}</p>
                </div>
              ))}
              {recommendation.agent_analysis.risks?.length > 0 && (
                <>
                  <strong>Risks and trade-offs</strong>
                  <ul>{recommendation.agent_analysis.risks.map((risk, index) => <li key={index}>{risk}</li>)}</ul>
                </>
              )}
            </div>
          )}
          <details>
            <summary>Scoring factors and evidence</summary>
            <ul>{Object.entries(recommendation.factors_used ?? {}).map(([key, factor]) => (
              <li key={key}>{key.replaceAll("_", " ")}: {factor.rating}/5 — {factor.rationale} ({factor.basis})</li>
            ))}</ul>
          </details>
        </section>
      )}

      {documents.length > 0 && (
        <section className="review-card">
          <h2>Generated Documents</h2>
          <ul>{documents.map((doc) => (
            <li key={doc.type}><a href={doc.download_url} target="_blank" rel="noreferrer">Download {doc.title}</a> ({doc.requirement_count} requirements)</li>
          ))}</ul>
        </section>
      )}

      {pipelineResult.escalations?.length > 0 && (
        <section className="review-card escalation"><h2>Items needing attention</h2><ul>{pipelineResult.escalations.map((item, i) => <li key={i}>{item}</li>)}</ul></section>
      )}

      <section className="review-card">
        <h2>Extracted Requirements</h2>
        <div className="table-scroll">
          <table>
            <thead><tr><th>ID / source</th><th>Requirement</th><th>Risk</th><th>Confidence</th></tr></thead>
            <tbody>{requirements.map((req) => (
              <tr key={req.id}>
                <td>{req.id}<br /><small>{req.source_slot ?? "source not linked"}</small></td>
                <td>
                  {req.statement}<br /><small>{req.category?.join(", ")}</small>
                  {req.acceptance_criteria?.length > 0 && (
                    <details className="review-criteria">
                      <summary>Acceptance criteria</summary>
                      <ul>{req.acceptance_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul>
                    </details>
                  )}
                </td>
                <td>{req.risk_level ?? "Not assessed"}</td>
                <td>{req.confidence_score}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      {pipelineResult.validation_notes?.length > 0 && (
        <section className="review-card"><h2>Analysis Notes</h2><ul>{pipelineResult.validation_notes.map((note, i) => <li key={i}>{note}</li>)}</ul></section>
      )}
      {sessionId && <small>Session: {sessionId}</small>}
    </div>
  );
}
