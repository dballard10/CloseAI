import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Menu,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  SendHorizontal,
  ShieldCheck,
  Trash2,
  UserRound,
  X,
} from "lucide-react";

type Role = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  createdAt: string;
};

type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
};

const STORAGE_KEY = "closeai:harness:chats:v1";
const ACTIVE_CHAT_KEY = "closeai:harness:active-chat:v1";
const MOCK_DELAY_MS = 760;

const samplePrompts = [
  "Draft a concise reply to my manager without exposing my personal details.",
  "Summarize this sensitive case note and preserve the important action items.",
  "Help rewrite this customer update after local de-identification.",
];

function nowIso() {
  return new Date().toISOString();
}

function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }

  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function createBlankChat(): ChatSession {
  const timestamp = nowIso();

  return {
    id: createId("chat"),
    title: "New chat",
    createdAt: timestamp,
    updatedAt: timestamp,
    messages: [],
  };
}

function createMessage(role: Role, content: string): ChatMessage {
  return {
    id: createId(role === "user" ? "user" : "assistant"),
    role,
    content,
    createdAt: nowIso(),
  };
}

function getStorage() {
  try {
    if (typeof window === "undefined") return null;
    const probe = "__closeai_storage_probe__";
    window.localStorage.setItem(probe, probe);
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch {
    return null;
  }
}

function loadChats(): ChatSession[] {
  const storage = getStorage();
  if (!storage) return [createBlankChat()];

  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return [createBlankChat()];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [createBlankChat()];

    const validChats = parsed.filter(isChatSession);
    return validChats.length > 0 ? validChats : [createBlankChat()];
  } catch {
    return [createBlankChat()];
  }
}

function isChatSession(value: unknown): value is ChatSession {
  if (!value || typeof value !== "object") return false;
  const chat = value as ChatSession;

  return (
    typeof chat.id === "string" &&
    typeof chat.title === "string" &&
    typeof chat.createdAt === "string" &&
    typeof chat.updatedAt === "string" &&
    Array.isArray(chat.messages) &&
    chat.messages.every(isChatMessage)
  );
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as ChatMessage;

  return (
    typeof message.id === "string" &&
    (message.role === "user" || message.role === "assistant") &&
    typeof message.content === "string" &&
    typeof message.createdAt === "string"
  );
}

function loadActiveChatId(chats: ChatSession[]) {
  const storage = getStorage();
  const savedId = storage?.getItem(ACTIVE_CHAT_KEY);

  if (savedId && chats.some((chat) => chat.id === savedId)) {
    return savedId;
  }

  return chats[0]?.id ?? createBlankChat().id;
}

function persistChats(chats: ChatSession[]) {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(chats));
  } catch {
    // localStorage can fail in private mode or when quota is exhausted.
  }
}

function persistActiveChat(chatId: string) {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.setItem(ACTIVE_CHAT_KEY, chatId);
  } catch {
    // localStorage can fail in private mode or when quota is exhausted.
  }
}

function makeTitle(content: string) {
  const firstLine = content.replace(/\s+/g, " ").trim();
  if (!firstLine) return "New chat";

  return firstLine.length > 42 ? `${firstLine.slice(0, 39).trim()}...` : firstLine;
}

function makeMockResponse(content: string) {
  const hasSensitiveHint = /\b(email|phone|ssn|address|patient|customer|manager|name|private|sensitive)\b/i.test(
    content,
  );

  if (hasSensitiveHint) {
    return [
      "Mock response from CloseAI Harness:",
      "",
      "I would first treat the sensitive parts of your prompt as locally protected context, send only a de-identified version to the closed model, then restore the useful references on your machine before showing the final answer.",
      "",
      "For this MVP, I am only simulating that round trip so you can test chat flow and local history.",
    ].join("\n");
  }

  return [
    "Mock response from CloseAI Harness:",
    "",
    "I can help with that. In the full harness, your prompt would be de-identified locally before the model sees it, and the response would be re-identified locally before it comes back into this conversation.",
    "",
    "This reply is mocked for the frontend MVP.",
  ].join("\n");
}

function formatRelativeTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function App() {
  const initialChats = useMemo(loadChats, []);
  const [chats, setChats] = useState<ChatSession[]>(initialChats);
  const [activeChatId, setActiveChatId] = useState(() => loadActiveChatId(initialChats));
  const [draft, setDraft] = useState("");
  const [isResponding, setIsResponding] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const messageEndRef = useRef<HTMLDivElement | null>(null);

  const activeChat = chats.find((chat) => chat.id === activeChatId) ?? chats[0];
  const sortedChats = useMemo(
    () => [...chats].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    [chats],
  );

  useEffect(() => {
    persistChats(chats);
  }, [chats]);

  useEffect(() => {
    if (activeChatId) persistActiveChat(activeChatId);
  }, [activeChatId]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [activeChat?.messages.length, isResponding]);

  function createNewChat() {
    const chat = createBlankChat();
    setChats((current) => [chat, ...current]);
    setActiveChatId(chat.id);
    setDraft("");
    setIsSidebarOpen(false);
  }

  function selectChat(chatId: string) {
    setActiveChatId(chatId);
    setDraft("");
    setIsSidebarOpen(false);
  }

  function deleteChat(chatId: string) {
    setChats((current) => {
      const remaining = current.filter((chat) => chat.id !== chatId);
      const nextChats = remaining.length > 0 ? remaining : [createBlankChat()];

      if (chatId === activeChatId) {
        setActiveChatId(nextChats[0].id);
      }

      return nextChats;
    });
  }

  function updateActiveChat(updater: (chat: ChatSession) => ChatSession) {
    setChats((current) => current.map((chat) => (chat.id === activeChatId ? updater(chat) : chat)));
  }

  function handleSubmit(event?: FormEvent) {
    event?.preventDefault();

    const content = draft.trim();
    if (!content || isResponding || !activeChat) return;

    const userMessage = createMessage("user", content);
    setDraft("");
    setIsResponding(true);

    updateActiveChat((chat) => {
      const wasUntitled = chat.messages.length === 0 && chat.title === "New chat";
      const timestamp = nowIso();

      return {
        ...chat,
        title: wasUntitled ? makeTitle(content) : chat.title,
        updatedAt: timestamp,
        messages: [...chat.messages, userMessage],
      };
    });

    window.setTimeout(() => {
      const assistantMessage = createMessage("assistant", makeMockResponse(content));
      updateActiveChat((chat) => ({
        ...chat,
        updatedAt: nowIso(),
        messages: [...chat.messages, assistantMessage],
      }));
      setIsResponding(false);
    }, MOCK_DELAY_MS);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="min-h-screen bg-[#080b10] text-zinc-100 antialiased">
      <div className="flex min-h-screen">
        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-[286px] flex-col border-r border-white/10 bg-[#0d1118]/95 shadow-glow backdrop-blur transition-transform duration-200 lg:static lg:translate-x-0 ${
            isSidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex h-16 items-center gap-3 border-b border-white/10 px-4">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-cyan-300/25 bg-cyan-300/10 text-cyan-200">
              <ShieldCheck size={19} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="truncate text-sm font-semibold tracking-wide text-white">CloseAI Harness</h1>
              <p className="truncate text-xs text-zinc-400">Private chat prototype</p>
            </div>
            <button
              className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/10 hover:text-white lg:hidden"
              type="button"
              aria-label="Close sidebar"
              onClick={() => setIsSidebarOpen(false)}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>

          <div className="p-3">
            <button
              className="flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.06] px-3 text-sm font-medium text-zinc-100 transition hover:border-cyan-300/40 hover:bg-cyan-300/10 hover:text-cyan-100"
              type="button"
              onClick={createNewChat}
            >
              <MessageSquarePlus size={17} aria-hidden="true" />
              New chat
            </button>
          </div>

          <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4" aria-label="Chat history">
            <div className="mb-2 px-2 text-xs font-medium uppercase tracking-[0.16em] text-zinc-500">
              Local history
            </div>
            <div className="space-y-1">
              {sortedChats.map((chat) => {
                const isActive = chat.id === activeChatId;

                return (
                  <div
                    className={`group flex items-center gap-1 rounded-lg border transition ${
                      isActive
                        ? "border-cyan-300/30 bg-cyan-300/10"
                        : "border-transparent hover:bg-white/[0.055]"
                    }`}
                    key={chat.id}
                  >
                    <button
                      className="min-w-0 flex-1 px-3 py-2.5 text-left"
                      type="button"
                      onClick={() => selectChat(chat.id)}
                    >
                      <div className="truncate text-sm font-medium text-zinc-100">{chat.title}</div>
                      <div className="mt-0.5 truncate text-xs text-zinc-500">
                        {chat.messages.length === 0
                          ? "No messages yet"
                          : `${chat.messages.length} message${chat.messages.length === 1 ? "" : "s"} · ${formatRelativeTime(
                              chat.updatedAt,
                            )}`}
                      </div>
                    </button>
                    <button
                      className="mr-1 rounded-md p-2 text-zinc-500 opacity-100 transition hover:bg-rose-500/10 hover:text-rose-200 lg:opacity-0 lg:group-hover:opacity-100"
                      type="button"
                      aria-label={`Delete ${chat.title}`}
                      onClick={() => deleteChat(chat.id)}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </div>
          </nav>

          <div className="border-t border-white/10 p-4">
            <div className="rounded-lg border border-emerald-300/20 bg-emerald-300/[0.07] px-3 py-2 text-xs leading-5 text-emerald-100/90">
              Local history only. Model replies are mocked for this frontend MVP.
            </div>
          </div>
        </aside>

        {isSidebarOpen ? (
          <button
            className="fixed inset-0 z-30 bg-black/45 lg:hidden"
            type="button"
            aria-label="Close sidebar overlay"
            onClick={() => setIsSidebarOpen(false)}
          />
        ) : null}

        <main className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-white/10 bg-[#080b10]/80 px-4 backdrop-blur md:px-6">
            <button
              className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/10 hover:text-white lg:hidden"
              type="button"
              aria-label="Open sidebar"
              onClick={() => setIsSidebarOpen(true)}
            >
              <Menu size={20} aria-hidden="true" />
            </button>
            <button
              className="hidden rounded-lg p-2 text-zinc-400 transition hover:bg-white/10 hover:text-white lg:inline-flex"
              type="button"
              aria-label="Sidebar is open"
              disabled
            >
              <PanelLeftOpen size={19} aria-hidden="true" />
            </button>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-white">{activeChat?.title ?? "New chat"}</div>
              <div className="truncate text-xs text-zinc-500">De-identification pipeline coming later</div>
            </div>
            <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 sm:flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
              Mock mode
            </div>
            <button
              className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/10 hover:text-white lg:hidden"
              type="button"
              aria-label="Toggle sidebar"
              onClick={() => setIsSidebarOpen((value) => !value)}
            >
              <PanelLeftClose size={19} aria-hidden="true" />
            </button>
          </header>

          <section className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto flex w-full max-w-3xl flex-col px-4 py-8 md:px-6">
                {activeChat && activeChat.messages.length > 0 ? (
                  <div className="space-y-6">
                    {activeChat.messages.map((message) => (
                      <MessageBubble key={message.id} message={message} />
                    ))}
                    {isResponding ? <PendingBubble /> : null}
                    <div ref={messageEndRef} />
                  </div>
                ) : (
                  <EmptyState onPromptClick={setDraft} />
                )}
              </div>
            </div>

            <div className="border-t border-white/10 bg-[#080b10]/92 px-4 py-4 backdrop-blur md:px-6">
              <form className="mx-auto max-w-3xl" onSubmit={handleSubmit}>
                <div className="rounded-xl border border-white/10 bg-[#111821] p-2 shadow-2xl shadow-black/20 transition focus-within:border-cyan-300/35">
                  <label className="sr-only" htmlFor="message">
                    Message CloseAI Harness
                  </label>
                  <textarea
                    id="message"
                    className="max-h-48 min-h-[54px] w-full resize-none bg-transparent px-3 py-3 text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-500"
                    placeholder="Message CloseAI Harness..."
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={handleComposerKeyDown}
                    disabled={isResponding}
                  />
                  <div className="flex items-center justify-between gap-3 px-1 pb-1">
                    <p className="truncate text-xs text-zinc-500">
                      Enter to send. Shift+Enter for a new line.
                    </p>
                    <button
                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-cyan-200 text-slate-950 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-500"
                      type="submit"
                      aria-label="Send message"
                      disabled={draft.trim().length === 0 || isResponding}
                    >
                      <SendHorizontal size={17} aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}

function EmptyState({ onPromptClick }: { onPromptClick: (prompt: string) => void }) {
  return (
    <div className="flex min-h-[calc(100vh-12rem)] flex-col justify-center">
      <div className="max-w-2xl">
        <div className="mb-5 inline-flex h-12 w-12 items-center justify-center rounded-xl border border-cyan-300/25 bg-cyan-300/10 text-cyan-100">
          <ShieldCheck size={24} aria-hidden="true" />
        </div>
        <h2 className="text-2xl font-semibold tracking-normal text-white md:text-3xl">CloseAI Harness</h2>
        <p className="mt-3 max-w-xl text-sm leading-6 text-zinc-400 md:text-base">
          A quiet chat surface for testing local de-identification, closed-model handoff, and local re-identification.
        </p>
      </div>
      <div className="mt-8 grid gap-2 sm:grid-cols-3">
        {samplePrompts.map((prompt) => (
          <button
            className="min-h-[96px] rounded-lg border border-white/10 bg-white/[0.045] p-4 text-left text-sm leading-5 text-zinc-300 transition hover:border-cyan-300/30 hover:bg-cyan-300/10 hover:text-cyan-100"
            key={prompt}
            type="button"
            onClick={() => onPromptClick(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const Icon = isUser ? UserRound : Bot;

  return (
    <article className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser ? (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-100">
          <Icon size={17} aria-hidden="true" />
        </div>
      ) : null}
      <div className={`max-w-[min(100%,42rem)] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div
          className={`whitespace-pre-wrap rounded-xl px-4 py-3 text-sm leading-6 ${
            isUser
              ? "bg-cyan-200 text-slate-950"
              : "border border-white/10 bg-[#101720] text-zinc-100"
          }`}
        >
          {message.content}
        </div>
        <time className="mt-1.5 px-1 text-xs text-zinc-600">{formatRelativeTime(message.createdAt)}</time>
      </div>
      {isUser ? (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.055] text-zinc-300">
          <Icon size={17} aria-hidden="true" />
        </div>
      ) : null}
    </article>
  );
}

function PendingBubble() {
  return (
    <article className="flex gap-3">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-100">
        <Bot size={17} aria-hidden="true" />
      </div>
      <div className="rounded-xl border border-white/10 bg-[#101720] px-4 py-3">
        <div className="flex h-6 items-center gap-1.5" aria-label="Assistant is responding">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-zinc-400" />
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-zinc-400 [animation-delay:160ms]" />
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-zinc-400 [animation-delay:320ms]" />
        </div>
      </div>
    </article>
  );
}

export default App;
