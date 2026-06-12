import { useEffect, useState } from "react";

import { getAiChatStatus, sendAiChatMessage } from "../api.js";

const unavailableMessage =
  "Local AI model is not available. Start Ollama and make sure qwen3:8b is installed.";

const appStarters = [
  "What opportunities should I work on next?",
  "Show me the best pursuits right now.",
  "Which opportunities are risky because they are as-needed?",
  "Which deadlines are coming up?",
  "Which opportunities need document review?",
  "Which no-bids should I ignore?",
];

const opportunityStarters = [
  "Is this opportunity worth pursuing?",
  "What is missing?",
  "What are the biggest risks?",
  "What should I verify next?",
];

const contextOptions = [
  { value: "auto", label: "Auto" },
  { value: "app_overview", label: "Whole App Overview" },
  { value: "pursuit", label: "Pursuit Queue" },
  { value: "deadlines", label: "Deadlines" },
  { value: "opportunity", label: "Current Opportunity only" },
];

function modeLabel(mode) {
  const match = contextOptions.find((option) => option.value === mode);
  return match ? match.label : mode || "Auto";
}

function contextUsedText(contextUsed) {
  if (!contextUsed) {
    return "";
  }
  const parts = [
    modeLabel(contextUsed.mode),
    `${contextUsed.opportunity_count ?? 0} opportunities`,
    contextUsed.read_only ? "Read-only" : "",
  ].filter(Boolean);
  return `Context used: ${parts.join(" · ")}`;
}

export default function LocalAIChat({
  context = null,
  compact = false,
  title = "Local AI Chat",
}) {
  const fixedOpportunityMode = Boolean(context?.opportunity_id);
  const [status, setStatus] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [contextMode, setContextMode] = useState(context?.mode || "auto");
  const [lastContextUsed, setLastContextUsed] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadStatus() {
      try {
        setLoadingStatus(true);
        const result = await getAiChatStatus();
        setStatus(result);
        setError(result.available ? "" : result.error || unavailableMessage);
      } catch {
        setStatus({ available: false, model: "qwen3:8b" });
        setError(unavailableMessage);
      } finally {
        setLoadingStatus(false);
      }
    }

    loadStatus();
  }, []);

  async function sendMessage(messageText = input) {
    const message = messageText.trim();
    if (!message || sending) {
      return;
    }
    const userMessage = { role: "user", content: message };
    setMessages((current) => [...current, userMessage]);
    setInput("");
    setSending(true);
    setError("");
    setLastContextUsed(null);
    try {
      const requestContext = {
        ...(context || {}),
        mode: fixedOpportunityMode ? "opportunity" : contextMode,
      };
      const result = await sendAiChatMessage(message, requestContext);
      if (!result.available) {
        setError(result.error || unavailableMessage);
        setStatus((current) => ({ ...(current || {}), available: false }));
        setLastContextUsed(result.context_used || null);
        return;
      }
      setStatus((current) => ({
        ...(current || {}),
        available: true,
        model: result.model || current?.model || "qwen3:8b",
      }));
      setMessages((current) => [
        ...current,
        { role: "assistant", content: result.answer || "" },
      ]);
      setLastContextUsed(result.context_used || null);
    } catch (err) {
      setError(err.message || unavailableMessage);
    } finally {
      setSending(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    sendMessage();
  }

  const available = Boolean(status?.available);
  const model = status?.model || "qwen3:8b";
  const starters = fixedOpportunityMode ? opportunityStarters : appStarters;
  const visibleContextOptions = fixedOpportunityMode
    ? contextOptions.filter((option) => option.value === "opportunity")
    : contextOptions.filter((option) => option.value !== "opportunity");

  return (
    <section className={compact ? "chat-panel compact-chat" : "chat-panel"}>
      <div className="chat-header">
        <div>
          <h1>{title}</h1>
          <p className="muted-text">
            Model: <strong>{model}</strong>
          </p>
        </div>
        <span className={`status-badge ${available ? "" : "status-unavailable"}`}>
          {loadingStatus ? "Checking..." : available ? "Available" : "Unavailable"}
        </span>
      </div>

      <p className="notice-text">
        Read-only app context enabled. Answers are based only on available app data and local model reasoning.
        Verify official solicitation documents before acting.
      </p>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="chat-context-row">
        <label>
          Context
          <select
            value={fixedOpportunityMode ? "opportunity" : contextMode}
            disabled={fixedOpportunityMode || sending}
            onChange={(event) => setContextMode(event.target.value)}
          >
            {visibleContextOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="starter-prompts">
        {starters.map((prompt) => (
          <button
            key={prompt}
            className="secondary-button"
            type="button"
            disabled={sending || !available}
            onClick={() => sendMessage(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>

      {lastContextUsed ? (
        <p className="muted-text">{contextUsedText(lastContextUsed)}</p>
      ) : null}

      <div className="chat-messages" aria-live="polite">
        {!messages.length ? (
          <p className="muted-text">
            Ask about current opportunities, deadlines, bid/no-bid status,
            as-needed risks, missing documents, requirements, or logistics.
          </p>
        ) : (
          messages.map((message, index) => (
            <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
              <strong>{message.role === "user" ? "You" : "Local AI"}</strong>
              <p>{message.content}</p>
            </div>
          ))
        )}
        {sending ? <p className="muted-text">Local AI is thinking...</p> : null}
      </div>

      <form className="chat-input-row" onSubmit={submit}>
        <textarea
          value={input}
          placeholder="Type a message..."
          rows={compact ? 2 : 3}
          onChange={(event) => setInput(event.target.value)}
        />
        <button
          className="primary-button"
          type="submit"
          disabled={sending || !available || !input.trim()}
        >
          {sending ? "Sending..." : "Send"}
        </button>
      </form>
    </section>
  );
}
