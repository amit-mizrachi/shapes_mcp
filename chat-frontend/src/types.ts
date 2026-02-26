export type Role = "user" | "assistant";

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface Message {
  role: Role;
  content: string;
  toolCalls?: ToolCall[];
}

export interface ChatRequest {
  messages: { role: Role; content: string }[];
}

export interface ChatResponse {
  answer: string;
  tool_calls: ToolCall[];
}
