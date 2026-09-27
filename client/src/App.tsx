import { useEffect, useRef, useState, type FormEvent } from "react";
import Markdown from "react-markdown";
import { streamChat, type ChatTurn } from "./chat";
import "./App.css";

interface Message {
  role: "user" | "assistant";
  content: string;
  error?: string;
  citations?: string[]
}

// Embedded in another site via widget.js: the parent page owns the launcher
// and the iframe chrome; we render the chat full-bleed and signal close /
// resize intents up via postMessage.
const EMBED = new URLSearchParams(window.location.search).has("embed");

function postToParent(message: { type: string; expanded?: boolean }) {
  // The signals carry nothing sensitive, so "*" is fine here; widget.js
  // validates the message *source* before acting on it.
  window.parent.postMessage(message, "*");
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  // One conversation thread per page load; the server checkpoints state by it.
  const threadRef = useRef(crypto.randomUUID());
  const bottomRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  function toggleExpanded() {
    const next = !expanded;
    setExpanded(next);
    postToParent({ type: "ask-ruud:resize", expanded: next });
  }

  useEffect(() => {
    if (!EMBED) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Escape steps back: first out of the expanded view, then closes.
      if (expanded) {
        setExpanded(false);
        postToParent({ type: "ask-ruud:resize", expanded: false });
      } else {
        postToParent({ type: "ask-ruud:close" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);

    const history: ChatTurn[] = [
      ...messages
        .filter((m) => m.content)
        .map((m): ChatTurn => ({
          role: m.role, content:
            m.content
        })),
      { role: "user", content: question },
    ];
    setMessages([
      ...messages,
      { role: "user", content: question },
      { role: "assistant", content: "" },
    ]);

    const patch = (update: Partial<Message>) =>
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], ...update };
        return next;
      });

    const abort = new AbortController();
    abortRef.current = abort;
    let content = "";
    const citations: string[] = [];
    try {
      for await (const event of streamChat(history, threadRef.current, abort.signal)) {
        if (event.type === "text") {
          content += event.text;
          patch({ content });
        } else if (event.type === "error") {
          patch({ error: event.message });
        } else if (event.type === "citation") {
          citations.push(event.title);
          patch({ citations: [...citations] });
        }
      }
    } catch (err) {
      if (!abort.signal.aborted) {
        patch({ error: err instanceof Error ? err.message : "Request failed" });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  return (
    <main className={EMBED ? "chat embed" : "chat"}>
      <header className="chat-header">
        <div>
          <h1>Ask Ruud</h1>
          <p>AI digital twin of Ruud Juffermans — ask me about my work.</p>
        </div>
        {EMBED && (
          <div className="embed-controls">
            <button
              type="button"
              onClick={toggleExpanded}
              aria-label={expanded ? "Shrink chat window" : "Expand chat window"}
              aria-pressed={expanded}
            >
              {expanded ? "⤡" : "⤢"}
            </button>
            <button
              type="button"
              onClick={() => postToParent({ type: "ask-ruud:close" })}
              aria-label="Close chat"
            >
              ×
            </button>
          </div>
        )}
      </header>

      <div className="messages">
        {messages.length === 0 && (
          <p className="empty">Ask a question to get started.</p>
        )}
        {messages.map((message, i) => (
          <div key={i} className={`message ${message.role}`}>
            <div className="bubble">
              {message.role === "assistant" ? (
                <Markdown>{message.content}</Markdown>
              ) : (
                message.content
              )}
              {message.role === "assistant" &&
                !message.content &&
                !message.error && <span className="typing">…</span>}
              {message.citations?.length ? (
                <div className="chips">
                  {message.citations.map((title) => (
                    <span key={title} className="chip">{title}</span>
                  ))}
                </div>
              ) : null}
              {message.error && <p className="error">{message.error}</p>}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={send}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask something…"
          aria-label="Your question"
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </main>
  );
}
