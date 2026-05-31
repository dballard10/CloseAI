"use client";

import {
  Bot,
  CheckCircle2,
  ExternalLink,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  SendHorizontal,
  ShieldCheck,
  Trash2,
  UserRound
} from "lucide-react";
import type { KeyboardEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type {
  ChatApproveResponse,
  ChatClassificationResponse,
  HealthResponse
} from "@/lib/types";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  weaveTraceUrl?: string | null;
};

type ChatSession = {
  id: string;
  title: string;
  messages: ChatMessage[];
  updatedAt: string;
};

type ProcessStage = "idle" | "classifying" | "checking" | "review" | "revising" | "consulting" | "finalizing" | "done" | "error";

const STORAGE_KEY = "closedai.chat.sessions.v1";
const APPROVAL_PREF_KEY = "closedai.chat.approval-required.v1";

const processSteps = [
  { label: "Classify", stages: ["classifying"] },
  { label: "Check", stages: ["checking"] },
  { label: "Review", stages: ["review", "revising"] },
  { label: "Consult", stages: ["consulting"] },
  { label: "Finalize", stages: ["finalizing", "done"] }
];

function makeId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptySession(): ChatSession {
  const now = new Date().toISOString();
  return {
    id: makeId(),
    title: "New chat",
    messages: [],
    updatedAt: now
  };
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function titleFromPrompt(prompt: string) {
  const compact = prompt.replace(/\s+/g, " ").trim();
  return compact.length > 42 ? `${compact.slice(0, 39)}...` : compact || "New chat";
}

function buildPromptWithHistory(messages: ChatMessage[], latestUserMessage: string) {
  if (messages.length === 0) {
    return latestUserMessage;
  }

  const transcript = messages
    .map((message) => {
      const speaker = message.role === "user" ? "User" : "Assistant";
      return `${speaker} (${new Date(message.timestamp).toISOString()}):\n${message.content}`;
    })
    .join("\n\n");

  return [
    "Conversation history in this chat:",
    transcript,
    "Latest user message:",
    `User:\n${latestUserMessage}`,
    "Answer the latest user message using the prior conversation as context."
  ].join("\n\n");
}

async function postJson<T extends object>(url: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = (await response.json()) as T | { error?: string };
  if (!response.ok) {
    throw new Error("error" in data && data.error ? data.error : `Request failed with ${response.status}`);
  }
  return data as T;
}

function stageIndex(stage: ProcessStage) {
  if (stage === "idle") return -1;
  if (stage === "error") return -1;
  return processSteps.findIndex((step) => step.stages.includes(stage));
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [input, setInput] = useState("");
  const [feedback, setFeedback] = useState("");
  const [approval, setApproval] = useState<ChatClassificationResponse | null>(null);
  const [stage, setStage] = useState<ProcessStage>("idle");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [approvalRequired, setApprovalRequired] = useState(true);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    const storedApproval = localStorage.getItem(APPROVAL_PREF_KEY);
    if (storedApproval) {
      setApprovalRequired(storedApproval !== "0");
    }
    if (stored) {
      try {
        const parsed = JSON.parse(stored) as ChatSession[];
        if (Array.isArray(parsed) && parsed.length > 0) {
          setSessions(parsed);
          setActiveId(parsed[0].id);
          setLoaded(true);
          return;
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
    }
    const first = emptySession();
    setSessions([first]);
    setActiveId(first.id);
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
    }
  }, [loaded, sessions]);

  useEffect(() => {
    let cancelled = false;
    async function pollHealth() {
      try {
        const response = await fetch("/api/health", { cache: "no-store" });
        const data = (await response.json()) as HealthResponse;
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth({ status: "offline", consult_pipeline: "offline/setup needed" });
      }
    }
    void pollHealth();
    const interval = window.setInterval(() => void pollHealth(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [sessions, activeId, approval, stage]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }, [input]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeId) ?? sessions[0],
    [activeId, sessions]
  );

  const updateActiveSession = useCallback(
    (updater: (session: ChatSession) => ChatSession) => {
      setSessions((current) =>
        current.map((session) => (session.id === activeId ? updater(session) : session))
      );
    },
    [activeId]
  );

  const appendMessage = useCallback(
    (message: ChatMessage, titleSeed?: string) => {
      updateActiveSession((session) => {
        const isFirstUserMessage = message.role === "user" && session.messages.length === 0;
        return {
          ...session,
          title: isFirstUserMessage && titleSeed ? titleFromPrompt(titleSeed) : session.title,
          messages: [...session.messages, message],
          updatedAt: message.timestamp
        };
      });
    },
    [updateActiveSession]
  );

  async function queryApprovedClassification(classification: ChatClassificationResponse) {
    if (!classification.externalCallAllowed) {
      appendMessage({
        id: makeId(),
        role: "assistant",
        content:
          classification.finalCheckerResult.explanation ||
          "The privacy gate did not pass, so the external consultant was not called.",
        timestamp: new Date().toISOString(),
        weaveTraceUrl: classification.weaveTraceUrl
      });
      setApproval(null);
      setFeedback("");
      setStage("error");
      return;
    }

    setStage("consulting");
    const result = await postJson<ChatApproveResponse>("/api/approve-and-query", {
      rawPrompt: classification.rawPrompt,
      sanitizedPrompt: classification.sanitizedPrompt,
      detectedEntities: classification.detectedEntities,
      preservedConcepts: classification.preservedConcepts
    });
    setStage("finalizing");
    appendMessage({
      id: makeId(),
      role: "assistant",
      content: result.finalAnswer,
      timestamp: new Date().toISOString(),
      weaveTraceUrl: result.weaveTraceUrl
    });
    setApproval(null);
    setFeedback("");
    setStage("done");
  }

  function startNewChat() {
    const next = emptySession();
    setSessions((current) => [next, ...current]);
    setActiveId(next.id);
    setApproval(null);
    setFeedback("");
    setInput("");
    setStage("idle");
    setMobileSidebarOpen(false);
  }

  function deleteChat(id: string) {
    setSessions((current) => {
      const remaining = current.filter((session) => session.id !== id);
      if (remaining.length === 0) {
        const next = emptySession();
        setActiveId(next.id);
        return [next];
      }
      if (id === activeId) {
        setActiveId(remaining[0].id);
      }
      return remaining;
    });
  }

  async function submitPrompt() {
    const rawPrompt = input.trim();
    if (!rawPrompt || approval || stage === "classifying" || stage === "consulting" || stage === "revising" || stage === "finalizing") {
      return;
    }
    const rawPromptWithHistory = buildPromptWithHistory(activeSession?.messages ?? [], rawPrompt);

    setInput("");
    setFeedback("");
    setApproval(null);
    setStage("classifying");
    appendMessage(
      {
        id: makeId(),
        role: "user",
        content: rawPrompt,
        timestamp: new Date().toISOString()
      },
      rawPrompt
    );

    try {
      setStage("checking");
      const classified = await postJson<ChatClassificationResponse>("/api/classify", {
        rawPrompt: rawPromptWithHistory
      });
      if (approvalRequired) {
        setApproval(classified);
        setStage("review");
        return;
      }
      await queryApprovedClassification(classified);
    } catch (error) {
      appendMessage({
        id: makeId(),
        role: "assistant",
        content: `Classification failed: ${(error as Error).message}`,
        timestamp: new Date().toISOString()
      });
      setStage("error");
    }
  }

  async function reviseClassification() {
    if (!approval || !feedback.trim()) return;
    setStage("revising");
    try {
      const revised = await postJson<ChatClassificationResponse>("/api/revise-classification", {
        rawPrompt: approval.rawPrompt,
        feedback: feedback.trim()
      });
      setApproval(revised);
      setFeedback("");
      setStage("review");
    } catch (error) {
      appendMessage({
        id: makeId(),
        role: "assistant",
        content: `Revision failed: ${(error as Error).message}`,
        timestamp: new Date().toISOString()
      });
      setStage("error");
    }
  }

  async function approveAndQuery() {
    if (!approval || !approval.externalCallAllowed) return;
    try {
      await queryApprovedClassification(approval);
    } catch (error) {
      appendMessage({
        id: makeId(),
        role: "assistant",
        content: `Approve-and-query failed: ${(error as Error).message}`,
        timestamp: new Date().toISOString()
      });
      setStage("error");
    }
  }

  function toggleApprovalRequired(nextValue: boolean) {
    setApprovalRequired(nextValue);
    localStorage.setItem(APPROVAL_PREF_KEY, nextValue ? "1" : "0");
    if (!nextValue && approval && !["consulting", "finalizing"].includes(stage)) {
      void queryApprovedClassification(approval);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitPrompt();
    }
  }

  const activeIndex = stageIndex(stage);
  const backendLive = health?.status === "ok";
  const waiting = ["classifying", "checking", "revising", "consulting", "finalizing"].includes(stage);
  const composerDisabled = Boolean(approval) || waiting;

  return (
    <main className="h-screen overflow-hidden bg-[#080b10] text-zinc-100">
      {mobileSidebarOpen ? (
        <button
          aria-label="Close sidebar overlay"
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      ) : null}

      <div className="flex h-full">
        <aside
          className={[
            "fixed inset-y-0 left-0 z-40 flex w-[286px] flex-col border-r border-white/10 bg-[#0b1017] transition-transform duration-200 md:static md:translate-x-0",
            mobileSidebarOpen ? "translate-x-0" : "-translate-x-full",
            sidebarCollapsed ? "md:w-[82px]" : "md:w-[286px]"
          ].join(" ")}
        >
          <div className="flex h-16 items-center gap-3 border-b border-white/10 px-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-200/15 text-cyan-200">
              <ShieldCheck size={22} />
            </div>
            {!sidebarCollapsed ? (
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-zinc-100">CloseAI Harness</div>
                <div className="truncate text-xs text-zinc-500">Private chat prototype</div>
              </div>
            ) : null}
          </div>

          <div className="space-y-4 p-4">
            <button
              className="flex h-10 w-full items-center justify-center rounded-lg border border-white/10 px-3 text-sm font-medium text-zinc-100 transition hover:border-cyan-300/35 hover:bg-cyan-300/10 hover:text-cyan-100"
              onClick={startNewChat}
            >
              {!sidebarCollapsed ? "New Chat" : "+"}
            </button>

            {!sidebarCollapsed ? (
              <div className="text-[11px] font-semibold tracking-[0.18em] text-zinc-600">LOCAL HISTORY</div>
            ) : null}
          </div>

          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 pb-3">
            {sessions.map((session) => {
              const active = session.id === activeId;
              return (
                <button
                  key={session.id}
                  className={[
                    "group flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition",
                    active
                      ? "border-cyan-300/30 bg-cyan-300/10"
                      : "border-transparent hover:border-white/10 hover:bg-white/[0.03]"
                  ].join(" ")}
                  onClick={() => {
                    setActiveId(session.id);
                    setMobileSidebarOpen(false);
                    setApproval(null);
                    setFeedback("");
                    setStage("idle");
                  }}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-zinc-200">
                      {sidebarCollapsed ? session.title.slice(0, 1).toUpperCase() : session.title}
                    </div>
                    {!sidebarCollapsed ? (
                      <div className="mt-1 flex items-center gap-2 text-xs text-zinc-600">
                        <span>{session.messages.length} msgs</span>
                        <span>{formatTime(session.updatedAt)}</span>
                      </div>
                    ) : null}
                  </div>
                  {!sidebarCollapsed ? (
                    <span
                      role="button"
                      tabIndex={0}
                      className="hidden rounded-md p-1 text-zinc-600 hover:bg-rose-400/10 hover:text-rose-300 group-hover:inline-flex"
                      onClick={(event) => {
                        event.stopPropagation();
                        deleteChat(session.id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          event.stopPropagation();
                          deleteChat(session.id);
                        }
                      }}
                    >
                      <Trash2 size={15} />
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>

          {!sidebarCollapsed ? (
            <div className="m-4 rounded-lg border border-emerald-300/15 bg-emerald-300/10 p-3 text-xs leading-5 text-emerald-100/85">
              Local history stays in this browser. Prompts are de-identified before the model call.
            </div>
          ) : null}
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 border-b border-white/10 bg-[#080b10]/80 backdrop-blur">
            <div className="flex h-16 items-center gap-3 px-4">
              <button
                aria-label="Open sidebar"
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300 hover:border-cyan-300/35 hover:text-cyan-100 md:hidden"
                onClick={() => setMobileSidebarOpen(true)}
              >
                <Menu size={18} />
              </button>
              <button
                aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                className="hidden h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-300 hover:border-cyan-300/35 hover:text-cyan-100 md:inline-flex"
                onClick={() => setSidebarCollapsed((value) => !value)}
              >
                {sidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
              </button>

              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-zinc-100">{activeSession?.title ?? "New chat"}</div>
                <div className="truncate text-xs text-zinc-500">{health?.consult_pipeline ?? "Checking backend status..."}</div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs text-zinc-300 sm:inline-flex">
                  <span>Approval</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={approvalRequired}
                    aria-label="Toggle approval review"
                    onClick={() => toggleApprovalRequired(!approvalRequired)}
                    className={[
                      "relative h-4 w-8 rounded-full border transition",
                      approvalRequired ? "border-cyan-200/50 bg-cyan-200/80" : "border-white/10 bg-zinc-700"
                    ].join(" ")}
                  >
                    <span
                      className={[
                        "absolute top-0.5 h-2.5 w-2.5 rounded-full bg-[#080b10] transition",
                        approvalRequired ? "left-[18px]" : "left-0.5"
                      ].join(" ")}
                    />
                  </button>
                </div>
                <button
                  className={[
                    "inline-flex h-7 items-center rounded-full border px-2.5 text-xs sm:hidden",
                    approvalRequired
                      ? "border-cyan-300/25 bg-cyan-300/10 text-cyan-100"
                      : "border-white/10 bg-white/[0.03] text-zinc-400"
                  ].join(" ")}
                  onClick={() => toggleApprovalRequired(!approvalRequired)}
                >
                  Approval
                </button>
                <div
                  className={[
                    "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs",
                    backendLive
                      ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
                      : "border-amber-300/20 bg-amber-300/10 text-amber-100"
                  ].join(" ")}
                >
                  <span className={["h-2 w-2 rounded-full", backendLive ? "bg-emerald-300" : "bg-amber-300"].join(" ")} />
                  {backendLive ? "live" : "offline"}
                </div>
              </div>
            </div>

            <div className="border-t border-white/[0.04] px-4 py-3">
              <div className="mx-auto flex max-w-3xl items-center gap-2">
                {processSteps.map((step, index) => {
                  const active = activeIndex === index;
                  const complete = activeIndex > index || stage === "done";
                  return (
                    <div key={step.label} className="flex flex-1 items-center gap-2">
                      <div
                        className={[
                          "h-2.5 w-2.5 shrink-0 rounded-full transition",
                          active ? "bg-cyan-200 shadow-[0_0_16px_rgba(165,243,252,0.75)]" : complete ? "bg-emerald-300" : "bg-zinc-700"
                        ].join(" ")}
                      />
                      <div className="h-px flex-1 rounded bg-white/10">
                        <div
                          className={[
                            "h-px rounded transition-all",
                            complete ? "w-full bg-emerald-300/70" : active ? "w-1/2 bg-cyan-200/80" : "w-0"
                          ].join(" ")}
                        />
                      </div>
                      <span className={["hidden text-[11px] sm:inline", active ? "text-cyan-100" : "text-zinc-600"].join(" ")}>
                        {step.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-8">
            <div className="mx-auto flex max-w-3xl flex-col gap-6">
              {activeSession?.messages.length ? (
                activeSession.messages.map((message) => <MessageBubble key={message.id} message={message} />)
              ) : (
                <div className="rounded-xl border border-white/10 bg-[#101720] p-6">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-cyan-100">
                    <ShieldCheck size={18} />
                    Private chat ready
                  </div>
                  <p className="max-w-2xl text-sm leading-6 text-zinc-400">
                    Send a prompt. CloseAI will classify and de-identify it first, then query the external consultant only after the gate passes.
                  </p>
                </div>
              )}

              {waiting ? <TypingIndicator /> : null}

              {approval ? (
                <ApprovalPanel
                  approval={approval}
                  feedback={feedback}
                  setFeedback={setFeedback}
                  revising={stage === "revising"}
                  approving={stage === "consulting" || stage === "finalizing"}
                  onRevise={() => void reviseClassification()}
                  onApprove={() => void approveAndQuery()}
                />
              ) : null}

              <div ref={bottomRef} />
            </div>
          </div>

          <div className="border-t border-white/[0.06] bg-[#080b10] px-4 py-4">
            <div className="mx-auto max-w-3xl rounded-xl border border-white/10 bg-[#111821] p-2 transition focus-within:border-cyan-300/35 focus-within:shadow-[0_0_28px_rgba(165,243,252,0.08)]">
              <div className="flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  rows={1}
                  disabled={composerDisabled}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  placeholder={approval ? "Approve or revise the classified prompt first..." : "Message CloseAI..."}
                  className="min-h-[44px] flex-1 resize-none border-0 bg-transparent px-3 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 focus:ring-0 disabled:cursor-not-allowed disabled:text-zinc-600"
                />
                <button
                  aria-label="Send message"
                  disabled={!input.trim() || composerDisabled}
                  onClick={() => void submitPrompt()}
                  className="mb-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-200 text-slate-950 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
                >
                  <SendHorizontal size={18} />
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const user = message.role === "user";
  return (
    <div className={["flex gap-3", user ? "justify-end" : "justify-start"].join(" ")}>
      {!user ? (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan-200/10 text-cyan-200">
          <Bot size={17} />
        </div>
      ) : null}

      <div className={["max-w-[82%]", user ? "items-end" : "items-start"].join(" ")}>
        <div
          className={[
            "rounded-xl px-4 py-3 text-sm leading-6",
            user
              ? "bg-cyan-200 text-slate-950"
              : "border border-white/10 bg-[#101720] text-zinc-100"
          ].join(" ")}
        >
          {user ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <MarkdownMessage content={message.content} />
          )}
          {!user && message.weaveTraceUrl ? (
            <a
              href={message.weaveTraceUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-cyan-300/20 px-2 py-1 text-xs font-medium text-cyan-100 hover:bg-cyan-300/10"
            >
              Open Weave trace
              <ExternalLink size={13} />
            </a>
          ) : null}
        </div>
        <div className={["mt-1 text-xs text-zinc-600", user ? "text-right" : "text-left"].join(" ")}>
          {formatTime(message.timestamp)}
        </div>
      </div>

      {user ? (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan-200 text-slate-950">
          <UserRound size={17} />
        </div>
      ) : null}
    </div>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ children, ...props }) => (
          <a
            {...props}
            target="_blank"
            rel="noreferrer"
            className="text-cyan-100 underline decoration-cyan-200/35 underline-offset-2 hover:text-cyan-50"
          >
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-3 border-l-2 border-cyan-200/40 pl-3 text-zinc-300">
            {children}
          </blockquote>
        ),
        code: ({ children, className }) => {
          const inline = !className;
          return inline ? (
            <code className="rounded border border-white/10 bg-black/25 px-1.5 py-0.5 text-[0.9em] text-cyan-100">
              {children}
            </code>
          ) : (
            <code className={className}>{children}</code>
          );
        },
        h1: ({ children }) => <h1 className="mb-3 text-xl font-semibold text-zinc-50">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-4 text-lg font-semibold text-zinc-50">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-2 mt-3 text-base font-semibold text-zinc-50">{children}</h3>,
        hr: () => <hr className="my-4 border-white/10" />,
        li: ({ children }) => <li className="pl-1">{children}</li>,
        ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-5">{children}</ol>,
        p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
        pre: ({ children }) => (
          <pre className="my-3 overflow-x-auto rounded-lg border border-white/10 bg-black/30 p-3 text-xs leading-5 text-zinc-100">
            {children}
          </pre>
        ),
        table: ({ children }) => (
          <div className="my-3 overflow-x-auto rounded-lg border border-white/10">
            <table className="w-full border-collapse text-left text-sm">{children}</table>
          </div>
        ),
        tbody: ({ children }) => <tbody className="divide-y divide-white/10">{children}</tbody>,
        td: ({ children }) => <td className="px-3 py-2 text-zinc-300">{children}</td>,
        th: ({ children }) => <th className="bg-white/[0.04] px-3 py-2 font-semibold text-zinc-100">{children}</th>,
        thead: ({ children }) => <thead className="border-b border-white/10">{children}</thead>,
        ul: ({ children }) => <ul className="my-3 list-disc space-y-1.5 pl-5">{children}</ul>
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-200/10 text-cyan-200">
        <Bot size={17} />
      </div>
      <div className="flex gap-1 rounded-xl border border-white/10 bg-[#101720] px-4 py-3">
        <span className="h-2 w-2 animate-pulse rounded-full bg-zinc-500" />
        <span className="h-2 w-2 animate-pulse rounded-full bg-zinc-500 [animation-delay:120ms]" />
        <span className="h-2 w-2 animate-pulse rounded-full bg-zinc-500 [animation-delay:240ms]" />
      </div>
    </div>
  );
}

function ApprovalPanel({
  approval,
  feedback,
  setFeedback,
  revising,
  approving,
  onRevise,
  onApprove
}: {
  approval: ChatClassificationResponse;
  feedback: string;
  setFeedback: (value: string) => void;
  revising: boolean;
  approving: boolean;
  onRevise: () => void;
  onApprove: () => void;
}) {
  const passed = approval.finalCheckerResult.passed && approval.externalCallAllowed;
  const leaked = approval.finalCheckerResult.leakedItems ?? [];
  return (
    <div className="flex gap-3">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan-200/10 text-cyan-200">
        <ShieldCheck size={17} />
      </div>
      <div className="flex-1 rounded-xl border border-white/10 bg-[#101720] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Review classified prompt</div>
            <div className="mt-1 text-xs text-zinc-500">The external consultant will only see this sanitized version.</div>
          </div>
          <span
            className={[
              "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
              passed
                ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
                : "border-amber-300/20 bg-amber-300/10 text-amber-100"
            ].join(" ")}
          >
            {passed ? "Checker passed" : "Needs review"}
          </span>
        </div>

        <pre className="mt-4 whitespace-pre-wrap rounded-lg bg-black/20 p-3 text-sm leading-6 text-zinc-200">
          {approval.sanitizedPrompt}
        </pre>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
            <div className="text-xs text-zinc-500">Utility preserved</div>
            <div className="mt-1 text-2xl font-semibold text-cyan-100">
              {Math.round(approval.utilityResult.utilityScore * 100)}%
            </div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
            <div className="text-xs text-zinc-500">Sensitive items detected</div>
            <div className="mt-1 text-2xl font-semibold text-cyan-100">{approval.detectedEntities.length}</div>
          </div>
        </div>

        {approval.finalCheckerResult.explanation ? (
          <p className="mt-4 text-sm leading-6 text-zinc-400">{approval.finalCheckerResult.explanation}</p>
        ) : null}

        {leaked.length > 0 ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {leaked.map((item) => (
              <span key={item} className="rounded-full border border-amber-300/20 bg-amber-300/10 px-2 py-1 text-xs text-amber-100">
                {item}
              </span>
            ))}
          </div>
        ) : null}

        {approval.weaveTraceUrl ? (
          <a
            href={approval.weaveTraceUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-cyan-100 hover:text-cyan-50"
          >
            Inspect classification in Weave
            <ExternalLink size={13} />
          </a>
        ) : null}

        <textarea
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          placeholder="Tell the local agent what to change before approval..."
          className="mt-4 min-h-[88px] w-full resize-none rounded-lg border border-white/10 bg-[#0b1017] px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-cyan-300/35 focus:ring-0"
        />

        <div className="mt-3 flex flex-wrap justify-end gap-2">
          <button
            disabled={!feedback.trim() || revising || approving}
            onClick={onRevise}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 px-3 text-sm font-medium text-zinc-100 hover:border-cyan-300/35 hover:bg-cyan-300/10 disabled:cursor-not-allowed disabled:text-zinc-600"
          >
            <RefreshCw size={16} className={revising ? "animate-spin" : ""} />
            Revise
          </button>
          <button
            disabled={!passed || revising || approving}
            onClick={onApprove}
            className="inline-flex h-10 items-center gap-2 rounded-lg bg-cyan-200 px-3 text-sm font-semibold text-slate-950 hover:bg-cyan-100 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
          >
            <CheckCircle2 size={16} />
            Approve and send
          </button>
        </div>
      </div>
    </div>
  );
}
