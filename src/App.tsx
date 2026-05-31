import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Menu,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
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

type BackendHealth = {
  status: string;
  provider: string;
  model: string;
  provider_configured: boolean;
  setup_message?: string | null;
};

type QuerySuccess = {
  model_response?: string;
  reidentified_response?: string;
};

type QueryFailure = {
  ok?: false;
  error?: {
    provider?: string;
    message?: string;
    setup_hint?: string;
  };
  checker_result?: CheckerResult;
  utility_result?: UtilityResult;
  classified_prompt?: string;
};

type Mode = "hr" | "legal" | "healthcare" | "education" | "general";
type Risk = "low" | "medium" | "high";

type SensitiveEntity = {
  text: string;
  type: string;
  risk: Risk;
  replacementHint?: string | null;
};

type CheckerResult = {
  passed: boolean;
  riskLevel: Risk;
  leakageTypes: string[];
  leakedItems: string[];
  explanation?: string | null;
  recommendedFix?: string | null;
};

type UtilityResult = {
  utilityScore: number;
  preservedConcepts: string[];
  missingUsefulContext: string[];
};

type ClassificationDraft = {
  session_id: string;
  mode: Mode;
  classified_prompt: string;
  detected_entities: SensitiveEntity[];
  checker_result: CheckerResult;
  utility_result: UtilityResult;
  external_call_allowed: boolean;
  repaired?: boolean;
  model_status?: string;
};

type PendingApproval = ClassificationDraft & {
  chatId: string;
  feedback: string;
  error?: string | null;
};

const STORAGE_KEY = "closeai:harness:chats:v1";
const ACTIVE_CHAT_KEY = "closeai:harness:active-chat:v1";

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

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) return {} as T;
  return JSON.parse(text) as T;
}

function providerLabel(provider: string) {
  if (provider === "openai") return "OpenAI";
  if (provider === "anthropic") return "Anthropic";
  if (provider === "wandb") return "W&B Inference";
  if (provider === "ollama") return "Ollama";
  if (provider === "echo") return "Echo";
  return provider;
}

function inferMode(content: string): Mode {
  const text = content.toLowerCase();
  if (/\b(hr|manager|employee|pip|performance improvement|medical leave)\b/.test(text)) return "hr";
  if (/\b(landlord|tenant|lease|deposit|lawsuit|settlement|eviction)\b/.test(text)) return "legal";
  if (/\b(patient|doctor|clinician|prescribed|symptoms|medication)\b/.test(text)) return "healthcare";
  if (/\b(student|professor|course|assignment|academic integrity|cheating)\b/.test(text)) return "education";
  return "general";
}

function makeSetupMessage(message?: string, setupHint?: string) {
  return [
    "CloseAI de-identified your prompt locally, but the model provider is not ready yet.",
    "",
    message ?? "The backend could not complete the model request.",
    setupHint ? `\n${setupHint}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function makeBackendUnavailableMessage() {
  return [
    "I could not reach the CloseAI backend.",
    "",
    "Run `just dev` from the repo root, then try again. For live OpenAI replies, add `OPENAI_API_KEY=...` to `.env`; for an offline smoke test, set `CLOSEAI_PROVIDER=echo`.",
  ].join("\n");
}

function App() {
  const initialChats = useMemo(loadChats, []);
  const [chats, setChats] = useState<ChatSession[]>(initialChats);
  const [activeChatId, setActiveChatId] = useState(() => loadActiveChatId(initialChats));
  const [draft, setDraft] = useState("");
  const [isResponding, setIsResponding] = useState(false);
  const [isRevisingDraft, setIsRevisingDraft] = useState(false);
  const [isApprovingDraft, setIsApprovingDraft] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isDesktopSidebarOpen, setIsDesktopSidebarOpen] = useState(true);
  const [backendHealth, setBackendHealth] = useState<BackendHealth | null>(null);
  const [isBackendReachable, setIsBackendReachable] = useState<boolean | null>(null);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

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

  useEffect(() => {
    resizeComposer();
  }, [draft]);

  useEffect(() => {
    window.addEventListener("resize", resizeComposer);

    return () => {
      window.removeEventListener("resize", resizeComposer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadBackendHealth() {
      try {
        const response = await fetch("/api/health");
        if (!response.ok) throw new Error(`health check failed: ${response.status}`);
        const health = await readJson<BackendHealth>(response);
        if (!cancelled) {
          setBackendHealth(health);
          setIsBackendReachable(true);
        }
      } catch {
        if (!cancelled) {
          setBackendHealth(null);
          setIsBackendReachable(false);
        }
      }
    }

    loadBackendHealth();
    const interval = window.setInterval(loadBackendHealth, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  function createNewChat() {
    const chat = createBlankChat();
    setChats((current) => [chat, ...current]);
    setActiveChatId(chat.id);
    setDraft("");
    setPendingApproval(null);
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
      if (pendingApproval?.chatId === chatId) {
        setPendingApproval(null);
      }

      return nextChats;
    });
  }

  function updateChat(chatId: string, updater: (chat: ChatSession) => ChatSession) {
    setChats((current) => current.map((chat) => (chat.id === chatId ? updater(chat) : chat)));
  }

  async function requestClassification(content: string): Promise<ClassificationDraft | string> {
    try {
      const response = await fetch("/api/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content, mode: inferMode(content) }),
      });
      const body = await readJson<ClassificationDraft & QueryFailure>(response);

      if (!response.ok) {
        return makeSetupMessage(body.error?.message, body.error?.setup_hint);
      }

      setIsBackendReachable(true);
      return body;
    } catch {
      setIsBackendReachable(false);
      return makeBackendUnavailableMessage();
    }
  }

  async function reviseClassification() {
    if (!pendingApproval || isRevisingDraft) return;
    const feedback = pendingApproval.feedback.trim();
    if (!feedback) return;

    setIsRevisingDraft(true);
    try {
      const response = await fetch("/api/revise-classification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: pendingApproval.session_id, feedback }),
      });
      const body = await readJson<ClassificationDraft & QueryFailure>(response);

      if (!response.ok) {
        setPendingApproval((current) =>
          current
            ? {
                ...current,
                error: body.error?.message ?? "The local agent could not revise the classified prompt.",
              }
            : current,
        );
        return;
      }

      setIsBackendReachable(true);
      setPendingApproval((current) =>
        current
          ? {
              ...body,
              chatId: current.chatId,
              feedback: "",
              error: null,
            }
          : current,
      );
    } catch {
      setIsBackendReachable(false);
      setPendingApproval((current) =>
        current
          ? {
              ...current,
              error: makeBackendUnavailableMessage(),
            }
          : current,
      );
    } finally {
      setIsRevisingDraft(false);
    }
  }

  async function approveClassification() {
    if (!pendingApproval || isApprovingDraft || !activeChat) return;
    const chatId = pendingApproval.chatId;

    setIsApprovingDraft(true);
    setIsResponding(true);
    try {
      const response = await fetch("/api/approve-and-query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: pendingApproval.session_id,
          approved_prompt: pendingApproval.classified_prompt,
        }),
      });
      const body = await readJson<QuerySuccess & QueryFailure>(response);

      if (!response.ok) {
        setPendingApproval((current) =>
          current
            ? {
                ...current,
                checker_result: body.checker_result ?? current.checker_result,
                utility_result: body.utility_result ?? current.utility_result,
                classified_prompt: body.classified_prompt ?? current.classified_prompt,
                error: body.error?.message ?? "The approved prompt could not be sent.",
              }
            : current,
        );
        return;
      }

      const assistantMessage = createMessage(
        "assistant",
        body.model_response || body.reidentified_response || "The model returned an empty response.",
      );
      updateChat(chatId, (chat) => ({
        ...chat,
        updatedAt: nowIso(),
        messages: [...chat.messages, assistantMessage],
      }));
      setPendingApproval(null);
      setIsBackendReachable(true);
    } catch {
      setIsBackendReachable(false);
      setPendingApproval((current) =>
        current
          ? {
              ...current,
              error: makeBackendUnavailableMessage(),
            }
          : current,
      );
    } finally {
      setIsApprovingDraft(false);
      setIsResponding(false);
    }
  }

  async function handleSubmit(event?: FormEvent) {
    event?.preventDefault();

    const content = draft.trim();
    if (!content || isResponding || !activeChat || pendingApproval?.chatId === activeChat.id) return;

    const chatId = activeChat.id;
    const userMessage = createMessage("user", content);
    setDraft("");
    setIsResponding(true);

    updateChat(chatId, (chat) => {
      const wasUntitled = chat.messages.length === 0 && chat.title === "New chat";
      const timestamp = nowIso();

      return {
        ...chat,
        title: wasUntitled ? makeTitle(content) : chat.title,
        updatedAt: timestamp,
        messages: [...chat.messages, userMessage],
      };
    });

    const classification = await requestClassification(content);
    if (typeof classification === "string") {
      const assistantMessage = createMessage("assistant", classification);
      updateChat(chatId, (chat) => ({
        ...chat,
        updatedAt: nowIso(),
        messages: [...chat.messages, assistantMessage],
      }));
      setIsResponding(false);
      return;
    }

    setPendingApproval({
      ...classification,
      chatId,
      feedback: "",
      error: null,
    });
    setIsResponding(false);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  function resizeComposer() {
    const composer = composerRef.current;
    if (!composer) return;

    const maxHeight = Math.min(440, Math.max(240, window.innerHeight * 0.56));
    composer.style.height = "auto";
    composer.style.maxHeight = `${maxHeight}px`;
    composer.style.height = `${Math.min(composer.scrollHeight, maxHeight)}px`;
    composer.style.overflowY = composer.scrollHeight > maxHeight ? "auto" : "hidden";
  }

  return (
    <div className="h-screen bg-[#080b10] text-zinc-100 antialiased">
      <div className="flex h-screen min-h-0">
        <aside
          className={`fixed inset-y-0 left-0 z-40 flex w-[286px] flex-col border-r border-white/10 bg-[#080b10] shadow-glow transition-transform duration-200 ${
            isSidebarOpen ? "translate-x-0" : "-translate-x-full"
          } ${isDesktopSidebarOpen ? "lg:static lg:flex lg:translate-x-0" : "lg:hidden"}`}
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
              {backendHealth?.provider_configured === false
                ? backendHealth.setup_message ?? "Add the provider key to .env, then restart the backend."
                : "Local history stays in this browser. Prompts are de-identified before the model call."}
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

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
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
              aria-label={isDesktopSidebarOpen ? "Collapse sidebar" : "Open sidebar"}
              onClick={() => setIsDesktopSidebarOpen((value) => !value)}
            >
              {isDesktopSidebarOpen ? (
                <PanelLeftClose size={19} aria-hidden="true" />
              ) : (
                <PanelLeftOpen size={19} aria-hidden="true" />
              )}
            </button>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-white">{activeChat?.title ?? "New chat"}</div>
              <div className="truncate text-xs text-zinc-500">
                {backendHealth
                  ? backendHealth.provider_configured
                    ? `Live backend via ${providerLabel(backendHealth.provider)}`
                    : `${providerLabel(backendHealth.provider)} setup needed`
                  : isBackendReachable === false
                    ? "Backend offline"
                    : "Connecting to backend"}
              </div>
            </div>
            <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-zinc-300 sm:flex">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  isBackendReachable === false || backendHealth?.provider_configured === false
                    ? "bg-amber-300"
                    : "bg-emerald-300"
                }`}
              />
              {isBackendReachable === false
                ? "Backend offline"
                : backendHealth?.provider_configured === false
                  ? "Setup needed"
                  : "Live API"}
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
                    {pendingApproval?.chatId === activeChat.id ? (
                      <ApprovalPanel
                        draft={pendingApproval}
                        isApproving={isApprovingDraft}
                        isRevising={isRevisingDraft}
                        onApprove={approveClassification}
                        onFeedbackChange={(feedback) =>
                          setPendingApproval((current) => (current ? { ...current, feedback } : current))
                        }
                        onRevise={reviseClassification}
                      />
                    ) : null}
                    {isResponding ? <PendingBubble /> : null}
                    <div ref={messageEndRef} />
                  </div>
                ) : (
                  <div ref={messageEndRef} className="min-h-[1px]">
                    {pendingApproval?.chatId === activeChat?.id ? (
                      <ApprovalPanel
                        draft={pendingApproval}
                        isApproving={isApprovingDraft}
                        isRevising={isRevisingDraft}
                        onApprove={approveClassification}
                        onFeedbackChange={(feedback) =>
                          setPendingApproval((current) => (current ? { ...current, feedback } : current))
                        }
                        onRevise={reviseClassification}
                      />
                    ) : null}
                  </div>
                )}
              </div>
            </div>

            <div className="bg-[#080b10] px-4 pb-4 pt-2 md:px-6">
              <form className="mx-auto max-w-3xl" onSubmit={handleSubmit}>
                <div className="rounded-xl border border-white/10 bg-[#111821] p-2 shadow-2xl shadow-black/20 transition focus-within:border-cyan-300/35">
                  <label className="sr-only" htmlFor="message">
                    Message CloseAI Harness
                  </label>
                  <textarea
                    id="message"
                    ref={composerRef}
                    className="min-h-[54px] w-full resize-none overflow-hidden bg-transparent px-3 py-3 text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-500"
                    placeholder={
                      pendingApproval?.chatId === activeChat?.id
                        ? "Approve or revise the classified prompt first..."
                        : "Message CloseAI Harness..."
                    }
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    onKeyDown={handleComposerKeyDown}
                    disabled={isResponding || pendingApproval?.chatId === activeChat?.id}
                  />
                  <div className="flex items-center justify-end px-1 pb-1">
                    <button
                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-cyan-200 text-slate-950 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-500"
                      type="submit"
                      aria-label="Send message"
                      disabled={
                        draft.trim().length === 0 ||
                        isResponding ||
                        pendingApproval?.chatId === activeChat?.id
                      }
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

function ApprovalPanel({
  draft,
  isApproving,
  isRevising,
  onApprove,
  onFeedbackChange,
  onRevise,
}: {
  draft: PendingApproval;
  isApproving: boolean;
  isRevising: boolean;
  onApprove: () => void;
  onFeedbackChange: (feedback: string) => void;
  onRevise: () => void;
}) {
  const checkerTone = draft.checker_result.passed
    ? "border-emerald-300/25 bg-emerald-300/[0.08] text-emerald-100"
    : "border-amber-300/25 bg-amber-300/[0.08] text-amber-100";
  const utility = Math.round(draft.utility_result.utilityScore * 100);

  return (
    <article className="flex gap-3">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-100">
        <ShieldCheck size={17} aria-hidden="true" />
      </div>
      <div className="w-full max-w-[min(100%,42rem)] rounded-xl border border-white/10 bg-[#101720] p-4 shadow-2xl shadow-black/20">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-white">Review classified prompt</h2>
            <p className="mt-1 text-xs leading-5 text-zinc-500">
              The larger model will only receive this version after approval.
            </p>
          </div>
          <div className={`rounded-lg border px-2.5 py-1 text-xs ${checkerTone}`}>
            {draft.checker_result.passed ? "Checker passed" : "Checker needs review"}
          </div>
        </div>

        <div className="rounded-lg border border-white/10 bg-black/20 p-3 text-sm leading-6 text-zinc-100">
          <pre className="whitespace-pre-wrap break-words font-sans">{draft.classified_prompt}</pre>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2">
            <div className="text-xs uppercase tracking-[0.14em] text-zinc-500">Utility</div>
            <div className="mt-1 text-sm font-medium text-zinc-100">{utility}% preserved</div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2">
            <div className="text-xs uppercase tracking-[0.14em] text-zinc-500">Detected</div>
            <div className="mt-1 text-sm font-medium text-zinc-100">
              {draft.detected_entities.length} sensitive item{draft.detected_entities.length === 1 ? "" : "s"}
            </div>
          </div>
        </div>

        {draft.checker_result.explanation ? (
          <p className="mt-3 text-sm leading-6 text-zinc-400">{draft.checker_result.explanation}</p>
        ) : null}

        {draft.checker_result.leakedItems.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {draft.checker_result.leakedItems.map((item) => (
              <span
                className="rounded-md border border-amber-300/25 bg-amber-300/10 px-2 py-1 text-xs text-amber-100"
                key={item}
              >
                {item}
              </span>
            ))}
          </div>
        ) : null}

        {draft.error ? (
          <div className="mt-3 flex gap-2 rounded-lg border border-amber-300/25 bg-amber-300/10 p-3 text-sm leading-6 text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{draft.error}</span>
          </div>
        ) : null}

        <div className="mt-4">
          <label className="sr-only" htmlFor="classification-feedback">
            Requested changes
          </label>
          <textarea
            id="classification-feedback"
            className="min-h-[86px] w-full resize-y rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm leading-6 text-zinc-100 outline-none placeholder:text-zinc-500 focus:border-cyan-300/35"
            placeholder="Tell the local agent what to change before approval..."
            value={draft.feedback}
            onChange={(event) => onFeedbackChange(event.target.value)}
            disabled={isApproving || isRevising}
          />
        </div>

        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.06] px-4 text-sm font-medium text-zinc-100 transition hover:border-cyan-300/40 hover:bg-cyan-300/10 disabled:cursor-not-allowed disabled:text-zinc-500"
            type="button"
            onClick={onRevise}
            disabled={draft.feedback.trim().length === 0 || isApproving || isRevising}
          >
            <RefreshCw className={`h-4 w-4 ${isRevising ? "animate-spin" : ""}`} aria-hidden="true" />
            {isRevising ? "Revising" : "Revise"}
          </button>
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-200 px-4 text-sm font-semibold text-slate-950 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-500"
            type="button"
            onClick={onApprove}
            disabled={isApproving || isRevising || !draft.checker_result.passed}
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            {isApproving ? "Sending" : "Approve and send"}
          </button>
        </div>
      </div>
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
