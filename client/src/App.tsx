import { useEffect, useRef, useState, type FormEvent } from "react";
import Markdown from "react-markdown";
import { streamChat, type ChatTurn } from "./chat";
import "./App.css";

interface Message {
  role: "user" | "assistant";
  content: string;
  error?: string;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function send(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);

    const history: ChatTurn[] = [
      ...messages
        .filter((m) => m.content)
        .map((m): ChatTurn => ({ role: m.role, content:
    m.content })),
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
    try {
      for await (const event of streamChat(history, abort.signal)) {
        if (event.type === "text") {
          content += event.text;
          patch({ content });
        } else if (event.type === "error") {
          patch({ error: event.message });
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
    <main className="chat">
      <header className="chat-header">
        <h1>Ask Ruud</h1>
        <p>A digital twin of Ruud Juffermans — ask about his work.</p>
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
