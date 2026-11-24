import { useEffect, useRef, useState } from "react";
import { sendChatMessage } from "../api.js";

const greeting = (mode) => mode === "one_shot"
  ? "Describe the personal loan app you want to build. You can send multiple messages, then end your description when you’re ready to generate requirements."
  : "Hi — let’s gather requirements for your loan origination app. What’s the core business goal, and who are your target customers?";

export default function ChatInterview({ sessionId, setSessionId, interviewComplete, setInterviewComplete, onPipelineResult }) {
  const [inputMode, setInputMode] = useState("interview");
  const [messages, setMessages] = useState(() => interviewComplete
    ? [{ role: "assistant", content: "This interview is complete. Open Results to view the analysis." }]
    : [{ role: "assistant", content: greeting("interview") }]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const chatWindowRef = useRef(null);
  const inputRef = useRef(null);

  function chooseMode(mode) {
    if (sessionId) return;
    setInputMode(mode);
    setMessages([{ role: "assistant", content: greeting(mode) }]);
  }

  useEffect(() => {
    const chatWindow = chatWindowRef.current;
    if (chatWindow) chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: "smooth" });
    if (!sending && !interviewComplete) inputRef.current?.focus();
  }, [messages, sending, interviewComplete]);

  async function submitChatTurn(text, finishInput = false) {
    try {
      const res = await sendChatMessage(sessionId, text, inputMode, finishInput);
      setSessionId(res.session_id);
      if (res.interview_complete) setInterviewComplete(true);
      const responseMessage = res.interview_complete && res.pipeline_result
        ? "Analysis is complete. Extracted requirements, the SDLC ranking, and documents are ready in Results."
        : res.assistant_message;
      if (responseMessage) setMessages((current) => [...current, { role: "assistant", content: responseMessage }]);
      if (res.interview_complete && res.pipeline_result) onPipelineResult(res.pipeline_result);
    } catch (err) {
      if (err.message.startsWith("409:")) {
        setInterviewComplete(true);
        setMessages((current) => [...current, { role: "assistant", content: "This input is complete. Open Results to view the analysis." }]);
      } else {
        setMessages((current) => [...current, { role: "assistant", content: `⚠️ ${err.message}` }]);
      }
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || sending || interviewComplete) return;
    setMessages((current) => [...current, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    try {
      await submitChatTurn(text);
    } finally {
      setSending(false);
    }
  }

  async function handleFinishDescription() {
    if (!sessionId || sending || interviewComplete) return;
    setSending(true);
    try {
      await submitChatTurn("", true);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat-panel">
      {!sessionId && !interviewComplete && (
        <div className="input-mode-picker" role="group" aria-label="How would you like to provide requirements?">
          <button className={inputMode === "interview" ? "active" : ""} onClick={() => chooseMode("interview")}>
            Guided interview
          </button>
          <button className={inputMode === "one_shot" ? "active" : ""} onClick={() => chooseMode("one_shot")}>
            Free-form description
          </button>
        </div>
      )}
      <div className="chat-window" ref={chatWindowRef}>
        {messages.map((message, index) => (
          <div key={index} className={`bubble ${message.role}`}>
            {message.content}
          </div>
        ))}
        {sending && <div className="bubble assistant">…</div>}
      </div>
      <div className="chat-input-row">
        <textarea
          ref={inputRef}
          value={input}
          rows={inputMode === "one_shot" ? 4 : 2}
          placeholder={interviewComplete ? "Input complete" : inputMode === "one_shot" ? "Add details about the app you want..." : "Type your answer..."}
          disabled={interviewComplete || sending}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.ctrlKey && event.key === "Enter") handleSend();
          }}
        />
        <button onClick={handleSend} disabled={sending || interviewComplete || !input.trim()}>
          Add details
        </button>
        {inputMode === "one_shot" && sessionId && !interviewComplete && (
          <button onClick={handleFinishDescription} disabled={sending}>
            End description
          </button>
        )}
      </div>
      {inputMode === "one_shot" && !interviewComplete && (
        <small className="input-mode-help">Send as many details as you need, then click End description to generate requirements.</small>
      )}
    </div>
  );
}
