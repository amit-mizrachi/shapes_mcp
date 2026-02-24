import React from "react";
import ReactMarkdown from "react-markdown";

interface Props {
  role: "user" | "assistant" | "error";
  content: string;
}

export default function ChatMessage({ role, content }: Props) {
  const isUser = role === "user";
  const isError = role === "error";

  return (
    <div className={`message ${isUser ? "user" : "assistant"} ${isError ? "error" : ""}`}>
      <div className="message-bubble">
        <span className="message-role">
          {isUser ? "You" : isError ? "Error" : "Assistant"}
        </span>
        <div className="message-content">
          {isUser ? (
            content
          ) : (
            <ReactMarkdown>{content}</ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
}
