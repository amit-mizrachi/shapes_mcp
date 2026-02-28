export type Role = "user" | "assistant";

export interface ToolCallEvent {
  status: "success" | "error" | "malformed";
  tool: string | null;
  arguments: Record<string, unknown> | null;
  error_message: string | null;
  retry_attempt: number | null;
}

export interface Message {
  role: Role;
  content: string;
  toolCalls?: ToolCallEvent[];
}

export interface ChatRequest {
  messages: { role: Role; content: string }[];
}

export interface ChatResponse {
  answer: string;
  tool_calls: ToolCallEvent[];
}
