import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Bot,
  GitBranch,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { fetchJSON } from "@/lib/api";
import { cn } from "@/lib/utils";

const TABS = [
  "Overview",
  "Workers",
  "Organization",
  "Chats",
  "Approvals",
  "Assets",
  "Evolution",
  "Import/Export",
  "Retention",
] as const;

type TabName = (typeof TABS)[number];

interface WorkerRow {
  worker_id: string;
  display_name: string;
  status: string;
  runtime_type: string;
  health_status?: string;
  risk_badges?: RiskBadge[];
}

interface ChatRow {
  thread_id: string;
  title: string;
  thread_type: string;
  status: string;
  read_only: boolean;
  valid_management_boundary: boolean;
  risk_badges?: RiskBadge[];
}

interface MessageRow {
  message_id: string;
  thread_id: string;
  message_type: string;
  delivery_status: string;
  visibility: string;
  body_preview: string;
  sensitive_flags: string[];
}

interface RiskBadge {
  code: string;
  label: string;
  severity: string;
}

interface Overview {
  workers: WorkerRow[];
  risk_badges: RiskBadge[];
  warnings: string[];
}

export default function WorkerAgentsPage() {
  const [activeTab, setActiveTab] = useState<TabName>("Overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [workers, setWorkers] = useState<WorkerRow[]>([]);
  const [chats, setChats] = useState<ChatRow[]>([]);
  const [messages, setMessages] = useState<MessageRow[]>([]);
  const [selectedThread, setSelectedThread] = useState<string>("");
  const [messageText, setMessageText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [actionResult, setActionResult] = useState<string>("");

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.thread_id === selectedThread),
    [chats, selectedThread],
  );
  const sendDisabled =
    !selectedChat ||
    selectedChat.read_only ||
    !selectedChat.valid_management_boundary ||
    !messageText.trim();

  useEffect(() => {
    void loadPage();
  }, []);

  useEffect(() => {
    if (!selectedThread) return;
    void loadHistory(selectedThread);
  }, [selectedThread]);

  async function loadPage() {
    setLoading(true);
    setError("");
    try {
      const [overviewData, workerData, chatData] = await Promise.all([
        fetchJSON<Overview>("/api/worker-agents/overview"),
        fetchJSON<WorkerRow[]>("/api/worker-agents/workers"),
        fetchJSON<ChatRow[]>("/api/worker-agents/chats"),
      ]);
      setOverview(overviewData);
      setWorkers(workerData);
      setChats(chatData);
      setSelectedThread((prev) => prev || chatData[0]?.thread_id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadHistory(threadId: string) {
    try {
      const data = await fetchJSON<{ messages: MessageRow[] }>(
        `/api/worker-agents/chats/${encodeURIComponent(threadId)}/history?limit=50`,
      );
      setMessages(data.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function sendMessage(message_type: "normal" | "mention" | "broadcast") {
    if (sendDisabled || !selectedThread) return;
    setActionResult("");
    try {
      const result = await fetchJSON<{ audit_ref: string; summary: string }>(
        `/api/worker-agents/chats/${encodeURIComponent(selectedThread)}/send`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sender_id: "user",
            text: messageText,
            message_type,
          }),
        },
      );
      setActionResult(`${result.summary} ${result.audit_ref}`);
      setMessageText("");
      await loadHistory(selectedThread);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center gap-2 text-sm">
        <Spinner />
        <span>Loading Worker Agents</span>
      </div>
    );
  }

  return (
    <main className="flex min-h-0 flex-col gap-4 normal-case tracking-normal">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-current/20 pb-3">
        <div>
          <h1 className="text-2xl font-semibold uppercase tracking-[0.08em] text-midground">
            Worker Agents
          </h1>
          <p className="text-sm text-midground/60">
            Managed organization state, approvals, chats, import/export, and retention.
          </p>
        </div>
        <Button ghost size="sm" onClick={() => void loadPage()}>
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </header>

      {error && (
        <div className="border border-red-400/50 bg-red-950/20 px-3 py-2 text-sm text-red-200">
          {error}
        </div>
      )}

      <nav className="flex gap-1 overflow-x-auto border-b border-current/10 pb-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={cn(
              "shrink-0 px-3 py-2 text-xs uppercase tracking-[0.1em]",
              activeTab === tab
                ? "border-b border-current text-midground"
                : "text-midground/55 hover:text-midground",
            )}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </nav>

      {activeTab === "Overview" && (
        <section className="grid gap-3 md:grid-cols-3">
          <Metric icon={Bot} label="Workers" value={overview?.workers.length ?? 0} />
          <Metric icon={AlertTriangle} label="Risks" value={overview?.risk_badges.length ?? 0} />
          <Metric icon={Archive} label="Warnings" value={overview?.warnings.length ?? 0} />
        </section>
      )}

      {activeTab === "Workers" && (
        <section className="overflow-x-auto">
          <DataTable
            rows={workers.map((worker) => ({
              id: worker.worker_id,
              name: worker.display_name,
              status: worker.status,
              runtime: worker.runtime_type,
              health: worker.health_status ?? "unknown",
              risk: worker.risk_badges?.map((badge) => badge.code).join(", ") ?? "",
            }))}
          />
        </section>
      )}

      {activeTab === "Chats" && (
        <section className="grid min-h-[28rem] gap-4 lg:grid-cols-[18rem_1fr]">
          <div className="min-h-0 overflow-auto border border-current/15">
            {chats.length === 0 ? (
              <EmptyState text="No managed chats" />
            ) : (
              chats.map((chat) => (
                <button
                  key={chat.thread_id}
                  onClick={() => setSelectedThread(chat.thread_id)}
                  className={cn(
                    "flex w-full flex-col gap-1 border-b border-current/10 px-3 py-2 text-left text-sm",
                    selectedThread === chat.thread_id && "bg-midground/10",
                  )}
                >
                  <span className="font-medium">{chat.title || chat.thread_id}</span>
                  <span className="text-xs text-midground/55">
                    {chat.thread_type} · {chat.status}
                    {chat.read_only ? " · read-only" : ""}
                  </span>
                </button>
              ))
            )}
          </div>
          <div className="flex min-h-0 flex-col gap-3">
            <div className="min-h-0 flex-1 overflow-auto border border-current/15">
              {messages.length === 0 ? (
                <EmptyState text="No controlled history messages" />
              ) : (
                messages.map((message) => (
                  <article key={message.message_id} className="border-b border-current/10 px-3 py-2">
                    <div className="flex flex-wrap gap-2 text-xs uppercase text-midground/55">
                      <span>{message.message_type}</span>
                      <span>{message.delivery_status}</span>
                      <span>{message.visibility}</span>
                    </div>
                    <p className="mt-1 text-sm">{message.body_preview}</p>
                    {message.sensitive_flags.length > 0 && (
                      <p className="mt-1 text-xs text-yellow-200">
                        {message.sensitive_flags.join(", ")}
                      </p>
                    )}
                  </article>
                ))
              )}
            </div>
            <div className="flex flex-col gap-2 border border-current/15 p-3">
              {selectedChat?.read_only && (
                <p className="text-xs text-midground/55">Thread is read-only.</p>
              )}
              <textarea
                value={messageText}
                onChange={(event) => setMessageText(event.target.value)}
                disabled={selectedChat?.read_only}
                className="min-h-20 resize-y border border-current/20 bg-transparent p-2 text-sm outline-none"
              />
              <div className="flex flex-wrap gap-2">
                <Button disabled={sendDisabled} size="sm" onClick={() => void sendMessage("normal")}>
                  <Send className="h-4 w-4" />
                  Send
                </Button>
                <Button disabled={sendDisabled} size="sm" onClick={() => void sendMessage("mention")}>
                  <MessageSquare className="h-4 w-4" />
                  Mention
                </Button>
                <Button disabled={sendDisabled} size="sm" onClick={() => void sendMessage("broadcast")}>
                  <ShieldCheck className="h-4 w-4" />
                  Broadcast
                </Button>
              </div>
              {actionResult && <p className="text-xs text-midground/60">{actionResult}</p>}
            </div>
          </div>
        </section>
      )}

      {activeTab === "Organization" && <Placeholder icon={GitBranch} text="Organization tree is available through the API." />}
      {activeTab === "Approvals" && <RemoteTable path="/api/worker-agents/approvals" />}
      {activeTab === "Assets" && <RemoteTable path="/api/worker-agents/assets" />}
      {activeTab === "Evolution" && <RemoteTable path="/api/worker-agents/evolution" />}
      {activeTab === "Import/Export" && <RemoteObject path="/api/worker-agents/export-manifest" />}
      {activeTab === "Retention" && <RemoteObject path="/api/worker-agents/cleanup-plan" />}
    </main>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Bot; label: string; value: number }) {
  return (
    <div className="border border-current/15 px-4 py-3">
      <Icon className="mb-3 h-5 w-5 text-midground/60" />
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs uppercase tracking-[0.1em] text-midground/55">{label}</div>
    </div>
  );
}

function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <EmptyState text="No rows" />;
  const columns = Object.keys(rows[0]);
  return (
    <table className="w-full min-w-[42rem] border-collapse text-sm">
      <thead>
        <tr className="border-b border-current/20 text-left text-xs uppercase text-midground/55">
          {columns.map((column) => (
            <th key={column} className="px-3 py-2 font-medium">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={String(row.id ?? index)} className="border-b border-current/10">
            {columns.map((column) => (
              <td key={column} className="max-w-80 truncate px-3 py-2">
                {String(row[column] ?? "")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="p-4 text-sm text-midground/55">{text}</div>;
}

function Placeholder({ icon: Icon, text }: { icon: typeof Bot; text: string }) {
  return (
    <div className="flex min-h-52 items-center justify-center gap-2 border border-current/15 text-sm text-midground/55">
      <Icon className="h-4 w-4" />
      <span>{text}</span>
    </div>
  );
}

function RemoteTable({ path }: { path: string }) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  useEffect(() => {
    void fetchJSON<Record<string, unknown>[]>(path).then(setRows);
  }, [path]);
  return <DataTable rows={rows} />;
}

function RemoteObject({ path }: { path: string }) {
  const [data, setData] = useState<unknown>(null);
  useEffect(() => {
    void fetchJSON<unknown>(path).then(setData);
  }, [path]);
  return (
    <pre className="overflow-auto border border-current/15 p-3 text-xs normal-case">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
