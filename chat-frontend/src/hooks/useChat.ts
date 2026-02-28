import { useState, useCallback } from "react";
import { sendMessage } from "../api/chat";
import type { Message, ToolCallEvent } from "../types";

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (content: string) => {
      const userMessage: Message = { role: "user", content };
      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);
      setError(null);

      try {
        const apiMessages = [...messages, userMessage].map(
          ({ role, content }) => ({ role, content })
        );
        const response = await sendMessage(apiMessages);

        const toolCalls: ToolCallEvent[] | undefined =
          response.tool_calls?.length > 0 ? response.tool_calls : undefined;

        const assistantMessage: Message = {
          role: "assistant",
          content: response.answer,
          toolCalls,
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Something went wrong."
        );
      } finally {
        setIsLoading(false);
      }
    },
    [messages]
  );

  return { messages, isLoading, error, send };
}
