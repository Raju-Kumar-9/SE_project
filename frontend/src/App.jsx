import { useState } from "react";
import ApprovalDashboard from "./components/ApprovalDashboard.jsx";
import ChatInterview from "./components/ChatInterview.jsx";
import AuditTrail from "./components/AuditTrail.jsx";

export default function App() {
  const [tab, setTab] = useState("chat");
  const [sessionId, setSessionId] = useState(null);
  const [interviewComplete, setInterviewComplete] = useState(false);
  const [pipelineResult, setPipelineResult] = useState(null);

  return (
    <div className="app-shell">
      <h1>Loan Origination RE-Agent System</h1>
      <p style={{ color: "#666" }}>Loan Origination Requirements and SDLC Review</p>

      <div className="tabs">
        <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
          Chat Interview
        </button>
        <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>
          Results
        </button>
        <button className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>
          Audit Trail
        </button>
      </div>

      <div className="tab-panel" hidden={tab !== "chat"}>
        <ChatInterview
          sessionId={sessionId}
          setSessionId={setSessionId}
          interviewComplete={interviewComplete}
          setInterviewComplete={setInterviewComplete}
          onPipelineResult={setPipelineResult}
        />
      </div>
      <div className="tab-panel" hidden={tab !== "review"}>
        <ApprovalDashboard sessionId={sessionId} pipelineResult={pipelineResult} />
      </div>
      <div className="tab-panel" hidden={tab !== "audit"}>
        <AuditTrail sessionId={sessionId} />
      </div>
    </div>
  );
}
