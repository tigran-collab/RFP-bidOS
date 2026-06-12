import { useEffect, useState } from "react";

import { getAiChatStatus, sendAiChatMessage } from "../api.js";

const unavailableMessage =
  "Local AI model is not available. Start Ollama and make sure qwen3:8b is installed.";

const starters = [
  "Is this opportunity worth pursuing?",
  "What information is missing?",
  "What are the biggest risks?",
  "Summarize this opportunity.",
  "What should I verify next?",
];

export default function LocalAIChat({
  context = null,
  compact = false,
  title = "Local AI Chat",
}) {
  const [status, setStatus] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
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
    try {
      const result = await sendAiChatMessage(message, context);
      if (!result.available) {
        setError(result.error || unavailableMessage);
        setStatus((current) => ({ ...(current || {}), available: false }));
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
        Answers are based only on available app data and local model reasoning.
        Verify official solicitation documents before acting.
      </p>

      {error ? <p className="error-text">{error}</p> : null}

      {context ? (
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
      ) : null}

      <div className="chat-messages" aria-live="polite">
        {!messages.length ? (
          <p className="muted-text">
            Ask about bid review, missing information, risks, scraper workflow,
            documents, requirements, or logistics.
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
