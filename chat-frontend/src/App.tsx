import { useChat } from "./hooks/useChat";
import { MessageList } from "./components/MessageList";
import { ChatInput } from "./components/ChatInput";

export function App() {
  const { messages, isLoading, error, send } = useChat();

  return (
    <div className="app">
      <header className="app-header">
        <h1>MCP Chat</h1>
      </header>

      <main className="app-main">
        <MessageList messages={messages} isLoading={isLoading} />
      </main>

      <footer className="app-footer">
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        <ChatInput onSend={send} disabled={isLoading} />
      </footer>
    </div>
  );
}
