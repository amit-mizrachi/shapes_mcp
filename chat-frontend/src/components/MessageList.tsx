import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Message } from "../types";
import { ToolCallTrace } from "./ToolCallTrace";
import { LoadingIndicator } from "./LoadingIndicator";
import { useAutoScroll } from "../hooks/useAutoScroll";

interface Props {
  messages: Message[];
  isLoading: boolean;
}

export function MessageList({ messages, isLoading }: Props) {
  const scrollRef = useAutoScroll([messages, isLoading]);

  return (
    <div className="message-list" ref={scrollRef} role="log" aria-live="polite">
      {messages.length === 0 && !isLoading && (
        <div className="empty-state">
          <h2>Data Assistant</h2>
          <p>Ask a question about the dataset to get started.</p>
          <div className="example-queries">
            <p>Try asking:</p>
            <ul>
              <li>"What columns are in the dataset?"</li>
              <li>"How many people live in London?"</li>
              <li>"What is the average salary?"</li>
            </ul>
          </div>
        </div>
      )}

      {messages.map((message, index) => {
        const isUser = message.role === "user";
        return (
          <div
            key={index}
            className={`message ${isUser ? "message-user" : "message-assistant"}`}
          >
            <div className="message-label">
              {isUser ? "You" : "Assistant"}
            </div>
            <div className="message-content">
              {isUser ? (
                <p>{message.content}</p>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              )}
            </div>
            {message.toolCalls && <ToolCallTrace toolCalls={message.toolCalls} />}
          </div>
        );
      })}

      {isLoading && <LoadingIndicator />}
    </div>
  );
}
