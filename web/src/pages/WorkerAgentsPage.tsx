import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  Bot,
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
  department_ids?: string[];
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

interface OrganizationNode {
  summary: OrganizationSummary;
  children: OrganizationNode[];
  warnings: string[];
}

interface OrganizationSummary {
  org_node_id: string;
  name: string;
  node_type: string;
  lifecycle: string;
  leader_kind: string;
  leader_worker_id?: string | null;
  member_worker_ids: string[];
  individual_worker_id?: string | null;
  collaboration_mode: string;
  read_only: boolean;
  risk_badges?: RiskBadge[];
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
  const [organization, setOrganization] = useState<OrganizationNode[]>([]);
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
      const [overviewData, workerData, chatData, organizationData] = await Promise.all([
        fetchJSON<Overview>("/api/worker-agents/overview"),
        fetchJSON<WorkerRow[]>("/api/worker-agents/workers"),
        fetchJSON<ChatRow[]>("/api/worker-agents/chats"),
        fetchJSON<OrganizationNode[]>("/api/worker-agents/organization"),
      ]);
      setOverview(overviewData);
      setWorkers(workerData);
      setChats(chatData);
      setOrganization(organizationData);
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

  async function openWorkerChat(workerId: string) {
    setActionResult("");
    try {
      const result = await fetchJSON<{ thread: ChatRow; disabled_reason?: string }>(
        `/api/worker-agents/workers/${encodeURIComponent(workerId)}/direct-chat`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      );
      if (!result.thread) {
        setError(result.disabled_reason || "Worker chat is not available.");
        return;
      }
      setChats((current) => upsertChat(current, result.thread));
      setSelectedThread(result.thread.thread_id);
      setActiveTab("Chats");
      await loadHistory(result.thread.thread_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function openDepartmentChat(orgNodeId: string) {
    const threadId = `dept-${orgNodeId}`;
    const chat = chats.find((item) => item.thread_id === threadId);
    if (!chat) {
      setError("Department chat is not available for this organization node.");
      return;
    }
    setSelectedThread(threadId);
    setActiveTab("Chats");
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
          <WorkerTable workers={workers} onOpenChat={(workerId) => void openWorkerChat(workerId)} />
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

      {activeTab === "Organization" && (
        <OrganizationTree
          nodes={organization}
          onOpenDepartmentChat={openDepartmentChat}
          onOpenWorkerChat={(workerId) => void openWorkerChat(workerId)}
        />
      )}
      {activeTab === "Approvals" && <RemoteTable path="/api/worker-agents/approvals" />}
      {activeTab === "Assets" && <RemoteTable path="/api/worker-agents/assets" />}
      {activeTab === "Evolution" && <RemoteTable path="/api/worker-agents/evolution" />}
      {activeTab === "Import/Export" && <RemoteObject path="/api/worker-agents/export-manifest" />}
      {activeTab === "Retention" && <RemoteObject path="/api/worker-agents/cleanup-plan" />}
    </main>
  );
}

function WorkerTable({
  workers,
  onOpenChat,
}: {
  workers: WorkerRow[];
  onOpenChat: (workerId: string) => void;
}) {
  if (workers.length === 0) return <EmptyState text="No workers" />;
  return (
    <table className="w-full min-w-[48rem] border-collapse text-sm">
      <thead>
        <tr className="border-b border-current/20 text-left text-xs uppercase text-midground/55">
          <th className="px-3 py-2 font-medium">worker</th>
          <th className="px-3 py-2 font-medium">status</th>
          <th className="px-3 py-2 font-medium">runtime</th>
          <th className="px-3 py-2 font-medium">health</th>
          <th className="px-3 py-2 font-medium">risk</th>
          <th className="px-3 py-2 font-medium">chat</th>
        </tr>
      </thead>
      <tbody>
        {workers.map((worker) => {
          const disabled = worker.status !== "enabled";
          return (
            <tr key={worker.worker_id} className="border-b border-current/10">
              <td className="px-3 py-2">
                <div className="font-medium">{worker.display_name || worker.worker_id}</div>
                <div className="text-xs text-midground/55">{worker.worker_id}</div>
              </td>
              <td className="px-3 py-2">{worker.status}</td>
              <td className="px-3 py-2">{worker.runtime_type}</td>
              <td className="px-3 py-2">{worker.health_status ?? "unknown"}</td>
              <td className="max-w-64 px-3 py-2 text-xs text-midground/65">
                {worker.risk_badges?.map((badge) => badge.code).join(", ") || ""}
              </td>
              <td className="px-3 py-2">
                <Button disabled={disabled} size="sm" onClick={() => onOpenChat(worker.worker_id)}>
                  <MessageSquare className="h-4 w-4" />
                  Open
                </Button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function OrganizationTree({
  nodes,
  onOpenDepartmentChat,
  onOpenWorkerChat,
}: {
  nodes: OrganizationNode[];
  onOpenDepartmentChat: (orgNodeId: string) => void;
  onOpenWorkerChat: (workerId: string) => void;
}) {
  if (nodes.length === 0) return <EmptyState text="No organization tree" />;
  return (
    <section className="flex flex-col border border-current/15">
      {nodes.map((node) => (
        <OrganizationNodeRow
          key={node.summary.org_node_id}
          node={node}
          depth={0}
          onOpenDepartmentChat={onOpenDepartmentChat}
          onOpenWorkerChat={onOpenWorkerChat}
        />
      ))}
    </section>
  );
}

function OrganizationNodeRow({
  node,
  depth,
  onOpenDepartmentChat,
  onOpenWorkerChat,
}: {
  node: OrganizationNode;
  depth: number;
  onOpenDepartmentChat: (orgNodeId: string) => void;
  onOpenWorkerChat: (workerId: string) => void;
}) {
  const summary = node.summary;
  const memberIds = summary.member_worker_ids ?? [];
  const onlyWorkerId = summary.individual_worker_id || (memberIds.length === 1 ? memberIds[0] : null);
  const canOpenDepartmentChat =
    !summary.read_only && summary.collaboration_mode === "department_group_chat";
  const canOpenWorkerChat = !summary.read_only && Boolean(onlyWorkerId);

  return (
    <div>
      <article
        className="border-b border-current/10 px-3 py-3"
        style={{ paddingLeft: `${12 + depth * 18}px` }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{summary.name || summary.org_node_id}</span>
              <span className="text-xs uppercase text-midground/55">{summary.node_type}</span>
              <span className="text-xs text-midground/55">{summary.lifecycle}</span>
              {summary.read_only && <span className="text-xs text-yellow-200">read-only</span>}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-midground/60">
              <span>mode: {summary.collaboration_mode}</span>
              <span>lead: {summary.leader_worker_id || summary.leader_kind}</span>
              <span>members: {memberIds.length}</span>
            </div>
            {(node.warnings.length > 0 || (summary.risk_badges?.length ?? 0) > 0) && (
              <div className="mt-2 space-y-1 text-xs text-yellow-200">
                {node.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
                {summary.risk_badges?.map((badge) => (
                  <p key={badge.code}>{badge.label || badge.code}</p>
                ))}
              </div>
            )}
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {canOpenDepartmentChat && (
              <Button size="sm" onClick={() => onOpenDepartmentChat(summary.org_node_id)}>
                <MessageSquare className="h-4 w-4" />
                Dept chat
              </Button>
            )}
            {canOpenWorkerChat && onlyWorkerId && (
              <Button size="sm" onClick={() => onOpenWorkerChat(onlyWorkerId)}>
                <Bot className="h-4 w-4" />
                Worker chat
              </Button>
            )}
          </div>
        </div>
      </article>
      {node.children.map((child) => (
        <OrganizationNodeRow
          key={child.summary.org_node_id}
          node={child}
          depth={depth + 1}
          onOpenDepartmentChat={onOpenDepartmentChat}
          onOpenWorkerChat={onOpenWorkerChat}
        />
      ))}
    </div>
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

function upsertChat(chats: ChatRow[], chat: ChatRow) {
  const existingIndex = chats.findIndex((item) => item.thread_id === chat.thread_id);
  if (existingIndex === -1) return [chat, ...chats];
  return chats.map((item, index) => (index === existingIndex ? chat : item));
}
