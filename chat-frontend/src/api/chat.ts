import type { ChatRequest, ChatResponse } from "../types";

const API_BASE = "/api";

export async function sendMessage(
  messages: ChatRequest["messages"]
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });

  if (!response.ok) {
    const status = response.status;
    if (status === 504) {
      throw new Error("Request timed out. Try a simpler question.");
    }
    throw new Error(`Request failed (${status}). Please try again.`);
  }

  return response.json();
}

export async function healthCheck(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/health`);
    const data = await response.json();
    return data.status === "ok";
  } catch {
    return false;
  }
}
