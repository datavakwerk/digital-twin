export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export type ChatEvent =
  | { type: "text"; text: string }
  | {
      type: "meta";
      model: string;
      inputTokens: number;
      outputTokens: number;
      cachedTokens: number;
      costUsd: number;
      latencyMs: number;
    }
  | { type: "error"; message: string }
  | { type: "citation"; title: string }
  | { type: "trace"; nodes: { node: string; ms: number | null }[]; guardFlags: string[] }
  | { type: "tool"; name: string }
  | { type: "done" };

export async function* streamChat(
  messages: ChatTurn[],
  threadId: string,
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ messages, thread_id: threadId }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      if (part.startsWith("data: ")) {
        yield JSON.parse(part.slice("data: ".length)) as ChatEvent;
      }
    }
  }
}