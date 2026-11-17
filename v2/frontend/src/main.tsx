import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Layers2,
  LayoutDashboard,
  PanelsTopLeft,
  CalendarDays,
  Clapperboard,
  ChartNoAxesCombined,
  KeyRound,
  Settings2,
  Users,
  Plus,
  LogOut,
  RefreshCw,
  ChevronRight,
  Check,
  Clock,
  AlertTriangle,
  ArrowUpRight,
  Sun,
  Moon,
  X,
  Upload,
  Search,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  ChevronLeft,
  Copy,
  Play,
  Eye,
  MessageCircle,
  Share2,
  MoreHorizontal,
} from "lucide-react";
import {
  api,
  post,
  upload,
  setCsrf,
  notifySessionChange,
  watchSessionChanges,
  number,
  date,
  size,
  ApiError,
  type User,
  type Connection,
  type Page,
  type Asset,
  type Job,
  type Reel,
  type Analytics,
  type Overview,
  type Sync,
} from "./api";
import "@fontsource-variable/inter/wght.css";
import "./styles.css";
import "./reference-theme.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 8000, refetchOnWindowFocus: false },
  },
});
const titles: Record<string, [string, string]> = {
  overview: ["Tổng quan", "Tổng quan"],
  pages: ["Pages", "Pages của bạn"],
  calendar: ["Lịch đăng", "Lịch đăng"],
  library: ["Thư viện", "Thư viện video"],
  analytics: ["Thống kê", "Hiệu quả nội dung"],
  connections: ["Kết nối", "Kết nối System User"],
  settings: ["Cài đặt", "Tài khoản & MCP"],
  users: ["Người dùng", "Người dùng"],
};
const statusNames: Record<string, string> = {
  working: "Hoạt động",
  unchecked: "Chưa kiểm tra",
  active: "Đang kết nối",
  disconnected: "Đã ngắt",
  needs_attention: "Cần kiểm tra",
  permission_limited: "Thiếu quyền",
  api_access_blocked: "Meta chặn API",
  invalid: "Token không hợp lệ",
  error: "Cần kiểm tra",
  rate_limited: "Chờ giới hạn",
  scheduled: "Chờ đăng",
  waiting_page: "Chờ Page",
  starting: "Tạo phiên",
  uploading: "Đang tải lên",
  processing: "Meta đang xử lý",
  publishing: "Đang đăng",
  verifying: "Đang xác minh",
  completed: "Hoàn tất",
  needs_user: "Cần xử lý",
  needs_review: "Cần xác minh",
  cancelled: "Đã hủy",
  available: "Đã cập nhật",
  partial: "Dữ liệu một phần",
  unavailable: "Chưa đọc được",
  pending: "Chờ đồng bộ",
  running: "Đang đồng bộ",
  never: "Chưa đồng bộ",
};
function Badge({ status, label }: { status: string; label?: string }) {
  const good = ["working", "active", "completed", "available"].includes(status),
    bad = [
      "invalid",
      "error",
      "needs_user",
      "needs_review",
      "api_access_blocked",
      "unavailable",
    ].includes(status);
  return (
    <span className={`badge ${good ? "good" : bad ? "warn" : ""}`}>
      <span />
      {label || statusNames[status] || status}
    </span>
  );
}
function Empty({
  icon: Icon = PanelsTopLeft,
  title,
  description,
  action,
}: {
  icon?: React.ElementType;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={25} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <AlertTriangle size={16} />
      <span>
        {error instanceof Error ? error.message : "Chưa tải được dữ liệu."}
      </span>
      {retry && (
        <button className="text-button" onClick={retry}>
          Thử lại
        </button>
      )}
    </div>
  );
}
function Loading() {
  return (
    <div className="loading">
      <LoaderCircle size={20} className="spin" /> Đang tải dữ liệu…
    </div>
  );
}
function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement;
    ref.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const nodes = ref.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
        );
        if (!nodes?.length) return;
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
      before?.focus();
    };
  }, []);
  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="Đóng" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
function Pager({
  total,
  offset,
  setOffset,
  limit = 25,
}: {
  total: number;
  offset: number;
  setOffset: (n: number) => void;
  limit?: number;
}) {
  return (
    <div className="pager">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} / ${number(total)}`
          : "0 mục"}
      </span>
      <div>
        <button
          aria-label="Trang trước"
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - limit))}
        >
          <ChevronLeft size={16} />
        </button>
        <span className="pager-position" aria-live="polite">
          Trang {Math.floor(offset / limit) + 1} /{" "}
          {Math.max(1, Math.ceil(total / limit))}
        </span>
        <button
          aria-label="Trang sau"
          disabled={offset + limit >= total}
          onClick={() => setOffset(offset + limit)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
function Avatar({ page }: { page: Page }) {
  const [bad, setBad] = useState(false);
  return (
    <span className="avatar">
      {!bad ? (
        <img
          src={page.avatar_url}
          alt=""
          loading="lazy"
          onError={() => setBad(true)}
        />
      ) : (
        page.name.slice(0, 2).toUpperCase()
      )}
    </span>
  );
}
function SearchBox({
  value,
  onChange,
  placeholder = "Tìm kiếm…",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="search">
      <Search size={16} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
function useData<T>(user: User, path: string, live = false) {
  return useQuery<T>({
    queryKey: [user.id, path],
    queryFn: ({ signal }) => api<T>(path, { signal }),
    refetchInterval: live ? 15000 : false,
  });
}
function SyncLine({
  sync,
  onSync,
  busy,
}: {
  sync?: Sync;
  onSync: () => void;
  busy: boolean;
}) {
  return (
    <div className="sync-line">
      <div>
        <span
          className={`live-dot ${sync?.status === "running" ? "pulse" : ""}`}
        />
        <span>
          {sync?.status === "running"
            ? "Đang lấy số liệu từ Meta…"
            : sync?.status === "pending"
              ? "Đang chờ đồng bộ…"
              : sync?.status === "error"
                ? sync.message
                : sync?.finished_at
                  ? `Cập nhật ${date(sync.finished_at)}`
                  : "Chưa đồng bộ"}
        </span>
      </div>
      <button
        className="subtle"
        onClick={onSync}
        disabled={busy || sync?.status === "running"}
      >
        <RefreshCw size={13} className={busy ? "spin" : ""} />
        Đồng bộ
      </button>
    </div>
  );
}

function ReelHistory({
  user,
  reel,
  onClose,
}: {
  user: User;
  reel: Reel;
  onClose: () => void;
}) {
  const [days, setDays] = useState(30),
    [metric, setMetric] = useState<"views" | "comments" | "shares">("views");
  const query = useData<{
    items: {
      observed_at: string;
      views: number | null;
      comments: number | null;
      shares: number | null;
    }[];
  }>(user, `/api/analytics/${reel.video_id}/history?days=${days}`);
  const points = query.data?.items || [],
    known = points.filter((p) => p[metric] != null);
  const max = Math.max(1, ...known.map((p) => p[metric] || 0));
  const first = points.length ? new Date(points[0].observed_at).getTime() : 0,
    last = points.length
      ? new Date(points[points.length - 1].observed_at).getTime()
      : 1;
  const x = (stamp: string) =>
    20 +
    ((new Date(stamp).getTime() - first) / Math.max(last - first, 1)) * 460;
  const y = (value: number) => 170 - (value / max) * 145;
  const segments: string[] = [];
  let segment = "";
  for (const p of points) {
    if (p[metric] == null) {
      if (segment) segments.push(segment);
      segment = "";
    } else
      segment +=
        (segment ? " L" : "M") + x(p.observed_at) + "," + y(p[metric]!);
  }
  if (segment) segments.push(segment);
  const delta =
    known.length > 1
      ? known[known.length - 1][metric]! - known[0][metric]!
      : null;
  return (
    <Modal title="Lịch sử thống kê" wide onClose={onClose}>
      <div className="detail-summary">
        <div>
          <strong>{reel.caption || reel.video_id}</strong>
          <small>{reel.page_name}</small>
        </div>
      </div>
      <div className="toolbar">
        <select
          aria-label="Chỉ số lịch sử"
          value={metric}
          onChange={(e) => setMetric(e.target.value as typeof metric)}
        >
          <option value="views">Lượt phát gồm phát lại</option>
          <option value="comments">Bình luận</option>
          <option value="shares">Chia sẻ</option>
        </select>
        <select
          aria-label="Khoảng thời gian thống kê"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value="7">7 ngày</option>
          <option value="30">30 ngày</option>
          <option value="90">90 ngày</option>
        </select>
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : known.length ? (
        <>
          <div className="history-total">
            <strong>{number(known[known.length - 1][metric])}</strong>
            <small>
              {delta == null
                ? "Cần thêm một lần lấy để so sánh"
                : `Chênh lệch hai mốc đã lấy: ${delta > 0 ? "+" : ""}${number(delta)}`}
            </small>
          </div>
          <svg
            className="history-chart"
            viewBox="0 0 500 190"
            role="img"
            aria-label="Các tổng tích lũy đã được lấy từ Meta"
          >
            <line x1="20" x2="480" y1="170" y2="170" />
            {segments.map((path, i) => (
              <path d={path} key={i} />
            ))}
            {known.map((p, i) => (
              <circle key={i} cx={x(p.observed_at)} cy={y(p[metric]!)} r="3">
                <title>
                  {date(p.observed_at)} · {number(p[metric])}
                </title>
              </circle>
            ))}
          </svg>
          <div className="chart-labels">
            <small>{date(points[0]?.observed_at)}</small>
            <small>{date(points[points.length - 1]?.observed_at)}</small>
          </div>
        </>
      ) : (
        <Empty
          icon={ChartNoAxesCombined}
          title="Chưa đủ số liệu cho chỉ số này"
          description="Đồng bộ sau khi token có quyền đọc. Hệ thống giữ rõ các lần chưa lấy được dữ liệu."
        />
      )}
      <p className="footnote">
        Đường biểu diễn dùng các tổng tích lũy đã lấy, không nội suy qua lần
        thiếu dữ liệu. Meta có thể hiệu chỉnh số đếm. Tối đa 500 mẫu gần nhất.
      </p>
    </Modal>
  );
}
function ReelTable({ items, user }: { items: Reel[]; user: User }) {
  const [selected, setSelected] = useState<Reel>();
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Nội dung / Page</th>
              <th className="numeric">Lượt phát</th>
              <th className="numeric">Bình luận</th>
              <th className="numeric">Chia sẻ</th>
              <th>Số liệu</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.video_id}>
                <td>
                  <div className="content-cell">
                    <span className="video-mark">
                      <Play size={14} />
                    </span>
                    <div>
                      {r.permalink_url ? (
                        <a
                          href={r.permalink_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {r.caption || `Video ${r.video_id}`}
                          <ArrowUpRight size={12} />
                        </a>
                      ) : (
                        <span>{r.caption || `Video ${r.video_id}`}</span>
                      )}
                      <small>
                        {r.page_name}
                        {r.published_at ? ` · ${date(r.published_at)}` : ""}
                      </small>
                    </div>
                  </div>
                </td>
                <td className="numeric" title={date(r.views_observed_at)}>
                  {number(r.views)}
                </td>
                <td className="numeric" title={date(r.comments_observed_at)}>
                  {number(r.comments)}
                </td>
                <td className="numeric" title={date(r.shares_observed_at)}>
                  {number(r.shares)}
                </td>
                <td>
                  <div
                    className="reel-state"
                    title={`Lần đọc gần nhất: ${date(r.observed_at)}`}
                  >
                    <Badge status={r.metric_status || "unavailable"} />
                    <button
                      className="icon-button history-button"
                      aria-label="Lịch sử"
                      title="Lịch sử số liệu"
                      onClick={() => setSelected(r)}
                    >
                      <ChartNoAxesCombined size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && (
        <ReelHistory
          user={user}
          reel={selected}
          onClose={() => setSelected(undefined)}
        />
      )}
    </>
  );
}

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  return (
    <main className="login-page">
      <div className="login-art">
        <div className="brand">
          <span>
            <Layers2 size={21} />
          </span>
          PageManager
        </div>
        <div>
          <span className="eyebrow">YOUR PAGES. YOUR SPACE.</span>
          <h1>
            Không gian riêng.
            <br />
            Tầm nhìn rộng hơn.
          </h1>
          <p>
            Quản lý Page, đặt lịch Reel và theo dõi hiệu quả trong một không
            gian gọn gàng.
          </p>
          <div className="login-pills">
            <span>
              <LockKeyhole size={14} />
              Kho cá nhân
            </span>
            <span>
              <CalendarDays size={14} />
              Lịch bền vững
            </span>
          </div>
        </div>
        <small>PageManager v2 · Rust + Python</small>
      </div>
      <div className="login-form">
        <div className="login-box">
          <span className="eyebrow">CHÀO MỪNG TRỞ LẠI</span>
          <h2>Đăng nhập kho của bạn</h2>
          <p>Page và token System User được lưu riêng theo tài khoản.</p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError(undefined);
              const values = new FormData(e.currentTarget);
              try {
                const result = await post<{ user: User }>(
                  "/api/auth/login",
                  Object.fromEntries(values),
                );
                onLogin(result.user);
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Tên đăng nhập
              <input
                name="username"
                autoComplete="username"
                required
                autoFocus
                maxLength={32}
              />
            </label>
            <label>
              Mật khẩu
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={1024}
              />
            </label>
            {error != null && <ErrorBox error={error} />}
            <button className="primary" disabled={busy}>
              {busy ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <>
                  Vào không gian làm việc
                  <ChevronRight size={16} />
                </>
              )}
            </button>
          </form>
          <div className="login-note">
            <ShieldCheck size={16} />
            Mỗi lần đăng nhập, hệ thống tự lấy lại chỉ số cho kho của bạn.
          </div>
        </div>
      </div>
    </main>
  );
}

function Dashboard({
  user,
  navigate,
  onCreate,
}: {
  user: User;
  navigate: (view: string) => void;
  onCreate: () => void;
}) {
  const query = useData<Overview>(user, "/api/overview", true);
  const jobs = useData<{ jobs: Job[] }>(
    user,
    "/api/reels?limit=4&status=pending&sort=scheduled_asc",
    true,
  );
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [selectedJob, setSelectedJob] = useState<Job>();
  async function sync() {
    setBusy(true);
    try {
      await post("/api/analytics/sync");
      await client.invalidateQueries({ queryKey: [user.id] });
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }
  if (query.isPending) return <Loading />;
  if (query.error)
    return <ErrorBox error={query.error} retry={() => query.refetch()} />;
  const data = query.data;
  const totals = data.analytics.totals;
  const metrics = [
    {
      label: "Lượt phát Reel",
      value: totals.views,
      known: totals.views_known,
      icon: Eye,
      note: "Gồm phát lại",
    },
    {
      label: "Bình luận",
      value: totals.comments,
      known: totals.comments_known,
      icon: MessageCircle,
      note: "Tổng tích lũy",
    },
    {
      label: "Chia sẻ",
      value: totals.shares,
      known: totals.shares_known,
      icon: Share2,
      note: "Tổng tích lũy",
    },
  ];
  return (
    <>
      <div className="dashboard-toolbar">
        <span>
          {new Intl.DateTimeFormat("vi-VN", {
            weekday: "long",
            day: "numeric",
            month: "long",
            timeZone: user.timezone,
          }).format(new Date())}
        </span>
        <SyncLine sync={data.sync} onSync={sync} busy={busy} />
      </div>
      {error != null && <ErrorBox error={error} />}
      <div className="stats-grid">
        {metrics.map(({ label, value, known, icon: Icon, note }, index) => {
          const coverage = totals.tracked
            ? Math.min(100, (known / totals.tracked) * 100)
            : 0;
          return (
            <article
              className={`stat-card ${index === 0 ? "featured" : ""}`}
              key={label}
            >
              <div className="stat-heading">
                <span>{label}</span>
                <span className="stat-symbol">
                  <Icon size={14} />
                </span>
              </div>
              <strong>{number(value, true)}</strong>
              <div className="stat-caption">
                <span>{note}</span>
                <span>
                  {totals.tracked
                    ? `${known}/${totals.tracked} nội dung`
                    : "Chưa có nội dung"}
                </span>
              </div>
              <div
                className="coverage-track"
                role="progressbar"
                aria-label={`${label}: số nội dung đã có số liệu`}
                aria-valuenow={known}
                aria-valuemin={0}
                aria-valuemax={Math.max(1, totals.tracked)}
              >
                <span style={{ width: `${coverage}%` }} />
              </div>
            </article>
          );
        })}
      </div>
      <div className="overview-strip">
        <button className="overview-link" onClick={() => navigate("pages")}>
          <PanelsTopLeft size={14} />
          {number(data.stats.pages)} Page
        </button>
        <button
          className="overview-link"
          onClick={() => navigate("connections")}
        >
          <KeyRound size={14} />
          {data.stats.working_connections}/{data.stats.connections} kết nối hoạt
          động
        </button>
        {data.scheduler.active_count > 0 && (
          <span>
            <Clock size={14} />
            {data.scheduler.active_count} tác vụ đang chạy
          </span>
        )}
        {data.stats.needs_attention > 0 && (
          <button
            className="text-button warning-text"
            onClick={() => navigate("connections")}
          >
            {data.stats.needs_attention} kết nối cần kiểm tra
            <ChevronRight size={14} />
          </button>
        )}
      </div>
      <div className="overview-content">
        <section className="content-overview" aria-label="Hiệu quả nội dung">
          <div className="section-heading">
            <div>
              <h3>Nội dung gần đây</h3>
              <p>Số liệu tích lũy theo từng nội dung.</p>
            </div>
            <button
              className="text-button"
              onClick={() => navigate("analytics")}
            >
              Xem tất cả
              <ArrowUpRight size={14} />
            </button>
          </div>
          {data.analytics.items.length ? (
            <ReelTable user={user} items={data.analytics.items} />
          ) : (
            <Empty
              icon={ChartNoAxesCombined}
              title="Chưa có số liệu nội dung"
              description="Kết nối Page để bắt đầu theo dõi hiệu quả."
              action={
                <button onClick={() => navigate("connections")}>
                  Thêm kết nối
                  <Plus size={14} />
                </button>
              }
            />
          )}
        </section>
        <section className="publish-panel" aria-label="Lịch đăng tiếp theo">
          <div className="section-heading">
            <h3>Tiếp theo</h3>
            <button
              className="icon-button"
              title="Xem lịch đăng"
              aria-label="Xem lịch đăng"
              onClick={() => navigate("calendar")}
            >
              <ArrowUpRight size={15} />
            </button>
          </div>
          {jobs.error ? (
            <ErrorBox error={jobs.error} />
          ) : jobs.isPending ? (
            <Loading />
          ) : jobs.data?.jobs.length ? (
            <div className="publish-list">
              {jobs.data.jobs.map((job) => (
                <button
                  className="publish-item"
                  key={job.id}
                  onClick={() => setSelectedJob(job)}
                >
                  <span className="publish-time">
                    {job.scheduled_local.slice(11, 16)}
                  </span>
                  <div>
                    <strong>{job.page_name}</strong>
                    <p>{job.caption || job.asset_name}</p>
                    <div className="publish-meta">
                      <span>
                        {job.scheduled_local.slice(8, 10)}/
                        {job.scheduled_local.slice(5, 7)} · {job.timezone}
                      </span>
                      <Badge status={job.status} />
                    </div>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="publish-empty">
              <span>
                <CalendarDays size={20} />
              </span>
              <div>
                <strong>Chưa có lịch chờ</strong>
                <p>Chuẩn bị nội dung cho lần đăng tiếp theo.</p>
              </div>
              <button onClick={onCreate}>
                Lên lịch
                <Plus size={13} />
              </button>
            </div>
          )}
        </section>
      </div>
      {selectedJob && (
        <JobDetail
          user={user}
          job={selectedJob}
          onClose={() => setSelectedJob(undefined)}
        />
      )}
    </>
  );
}

function Connections({ user }: { user: User }) {
  const [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [editing, setEditing] = useState<Connection | null | undefined>(),
    [actions, setActions] = useState<Connection>(),
    [confirm, setConfirm] = useState<Connection>(),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const query = useData<{ items: Connection[]; total: number }>(
    user,
    `/api/connections?limit=25&offset=${offset}&search=${encodeURIComponent(search)}`,
  );
  const client = useQueryClient();
  async function action(path: string, value: unknown = {}) {
    setBusy(true);
    setError(undefined);
    try {
      await post(path, value);
      await client.invalidateQueries({ queryKey: [user.id] });
      setConfirm(undefined);
      setActions(undefined);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="toolbar">
        <SearchBox
          value={search}
          onChange={(v) => {
            setSearch(v);
            setOffset(0);
          }}
          placeholder="Tìm kết nối…"
        />
        <button className="primary" onClick={() => setEditing(null)}>
          <Plus size={16} />
          Thêm System User
        </button>
      </div>
      <div className="hint">
        <LockKeyhole size={15} />
        Token được mã hóa và chỉ sử dụng phía máy chủ. Mỗi kết nối thuộc kho của
        bạn.
      </div>
      {error != null && <ErrorBox error={error} />}{" "}
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} retry={() => query.refetch()} />
      ) : query.data.items.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Kết nối</th>
                  <th>Business ID</th>
                  <th>Pages</th>
                  <th>Tình trạng</th>
                  <th>Kiểm tra gần nhất</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <div className="connection-name">
                        <span className="small-icon">
                          <KeyRound size={16} />
                        </span>
                        <div>
                          {c.label}
                          <small>
                            System User · {c.identity_name || "Chưa xác nhận"}
                          </small>
                        </div>
                      </div>
                    </td>
                    <td>{c.business_id || "—"}</td>
                    <td>{c.page_count}</td>
                    <td>
                      <Badge status={c.connected ? c.status : "disconnected"} />
                      {c.error && (
                        <small className="warning-text">{c.error}</small>
                      )}
                    </td>
                    <td className="connection-checked">{date(c.checked_at)}</td>
                    <td>
                      <button
                        className="icon-button connection-menu"
                        aria-label={`Thao tác với ${c.label}`}
                        title="Thao tác kết nối"
                        onClick={() => {
                          setError(undefined);
                          setActions(c);
                        }}
                      >
                        <MoreHorizontal size={17} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            total={query.data.total}
            offset={offset}
            setOffset={setOffset}
          />
        </>
      ) : (
        <Empty
          icon={KeyRound}
          title={
            search ? "Không tìm thấy kết nối" : "Kết nối System User đầu tiên"
          }
          description="Nhập token của System User đã được gán quyền trên Page và ứng dụng Meta."
          action={
            <button onClick={() => setEditing(null)}>
              <Plus size={15} />
              Thêm kết nối
            </button>
          }
        />
      )}{" "}
      {actions && (
        <Modal
          title={actions.label}
          onClose={() => !busy && setActions(undefined)}
        >
          <div className="connection-action-list">
            <button
              disabled={busy || !actions.connected}
              onClick={() => action(`/api/connections/${actions.id}/check`)}
            >
              <ShieldCheck size={18} />
              <span>
                Kiểm tra token
                <small>Xác nhận quyền và trạng thái kết nối</small>
              </span>
              <ChevronRight size={15} />
            </button>
            <button
              disabled={busy || !actions.connected}
              onClick={() => action(`/api/connections/${actions.id}/sync`)}
            >
              <RefreshCw size={18} />
              <span>
                Đồng bộ Pages
                <small>Lấy lại danh sách Page từ System User</small>
              </span>
              <ChevronRight size={15} />
            </button>
            <button
              disabled={busy}
              onClick={() => {
                setEditing(actions);
                setActions(undefined);
              }}
            >
              <Settings2 size={18} />
              <span>Chỉnh sửa kết nối</span>
              <ChevronRight size={15} />
            </button>
            {actions.connected && (
              <button
                disabled={busy}
                className="warning-text"
                onClick={() => {
                  setConfirm(actions);
                  setActions(undefined);
                }}
              >
                <LogOut size={18} />
                <span>Ngắt kết nối</span>
                <ChevronRight size={15} />
              </button>
            )}
          </div>
          {error != null && <ErrorBox error={error} />}
        </Modal>
      )}
      {editing !== undefined && (
        <ConnectionForm
          user={user}
          connection={editing}
          onClose={() => setEditing(undefined)}
        />
      )}{" "}
      {confirm && (
        <Modal title="Ngắt kết nối?" onClose={() => setConfirm(undefined)}>
          <p>
            Ngắt <strong>{confirm.label}</strong> sẽ xóa token đã lưu của kết
            nối này. Lịch chưa chạy dùng nguồn này sẽ cần xử lý lại.
          </p>
          <div className="modal-footer">
            <button onClick={() => setConfirm(undefined)}>Quay lại</button>
            <button
              className="danger"
              disabled={busy}
              onClick={() =>
                action(`/api/connections/${confirm.id}/disconnect`, {
                  revision: confirm.revision,
                })
              }
            >
              Ngắt kết nối
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

function ConnectionForm({
  user,
  connection,
  onClose,
}: {
  user: User;
  connection: Connection | null;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  return (
    <Modal
      title={
        connection ? "Sửa kết nối System User" : "Thêm kết nối System User"
      }
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          const fields = Object.fromEntries(new FormData(e.currentTarget));
          const value = {
            ...fields,
            token_type: "system_user",
            app_id: fields.app_id || null,
            business_id: fields.business_id || null,
            token: fields.token || null,
            ...(connection ? { revision: connection.revision } : {}),
          };
          try {
            await api(
              `/api/connections${connection ? "/" + connection.id : ""}`,
              {
                method: connection ? "PUT" : "POST",
                body: JSON.stringify(value),
              },
            );
            await client.invalidateQueries({ queryKey: [user.id] });
            onClose();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Tên kết nối
          <input
            name="label"
            defaultValue={connection?.label}
            placeholder="Ví dụ: BM Home"
            required
            maxLength={100}
          />
        </label>
        <div className="form-grid">
          <label>
            Business ID
            <input
              name="business_id"
              defaultValue={connection?.business_id || ""}
              inputMode="numeric"
              pattern="[0-9]{1,32}"
            />
          </label>
          <label>
            App ID
            <input
              name="app_id"
              defaultValue={connection?.app_id || ""}
              inputMode="numeric"
              pattern="[0-9]{1,32}"
            />
          </label>
        </div>
        <label>
          {connection
            ? "Token mới · để trống để giữ token hiện tại"
            : "System User access token"}
          <textarea
            name="token"
            required={!connection}
            autoComplete="off"
            spellCheck={false}
            rows={3}
            maxLength={8192}
          />
        </label>
        <div className="hint">
          <ShieldCheck size={16} />
          Sau khi lưu, dùng Kiểm tra và Đồng bộ Pages để xác nhận tài sản được
          cấp quyền.
        </div>
        {error != null && <ErrorBox error={error} />}
        <div className="modal-footer">
          <button type="button" onClick={onClose}>
            Hủy
          </button>
          <button className="primary" disabled={busy}>
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Check size={16} />
            )}
            Lưu kết nối
          </button>
        </div>
      </form>
    </Modal>
  );
}

function PageCard({ page, onSelect }: { page: Page; onSelect: () => void }) {
  const followers = page.details?.followers_count;
  const followerCount =
    typeof followers === "number" &&
    Number.isSafeInteger(followers) &&
    followers >= 0
      ? followers
      : null;
  const stats = page.analytics;
  const sources = page.connections
    .map((connection) => connection.label)
    .join(", ");
  const metrics = [
    {
      label: "Người theo dõi",
      value: followerCount,
      detail: "Số người theo dõi được đọc từ Page.",
    },
    {
      label: "Lượt phát Reel",
      value: stats?.views,
      detail: `Tổng tích lũy · ${stats?.views_known ?? 0}/${stats?.tracked ?? 0} Reel có số liệu.`,
    },
    {
      label: "Bình luận",
      value: stats?.comments,
      detail: `Tổng tích lũy · ${stats?.comments_known ?? 0}/${stats?.tracked ?? 0} Reel có số liệu.`,
    },
    {
      label: "Chia sẻ",
      value: stats?.shares,
      detail: `Tổng tích lũy · ${stats?.shares_known ?? 0}/${stats?.tracked ?? 0} Reel có số liệu.`,
    },
  ];
  return (
    <article className="page-card" aria-label={page.name}>
      <div className="page-card-header">
        <button
          className="page-card-identity"
          onClick={onSelect}
          aria-label={`Chi tiết ${page.name}`}
          aria-description={`Meta Page ID: ${page.id}. ${page.category || "Page"}. ${page.can_publish ? "Sẵn sàng đăng" : "Chưa sẵn sàng đăng"}`}
        >
          <Avatar page={page} />
          <span>
            <strong title={page.name}>{page.name}</strong>
            <small title={`Meta Page ID: ${page.id}`}>UID: {page.id}</small>
          </span>
        </button>
        <span className="page-card-labels">
          <Badge
            status={page.status}
            label={page.status === "active" ? "Hoạt động" : undefined}
          />
          <small
            title={`${page.category || "Page"} · ${page.can_publish ? "Sẵn sàng đăng" : "Chưa sẵn sàng đăng"}`}
          >
            {page.can_publish && <Check size={12} />}
            {page.category || "Page"}
          </small>
        </span>
      </div>
      <dl className="page-card-metrics">
        {metrics.map((metric) => (
          <div key={metric.label} title={metric.detail}>
            <dt>{metric.label}</dt>
            <dd title={number(metric.value)}>{number(metric.value)}</dd>
          </div>
        ))}
      </dl>
      <div className="page-card-note">
        <span>{number(stats?.tracked ?? 0)} Reel theo dõi</span>
        <span title="Lượt phát, bình luận và chia sẻ là tổng tích lũy trọn đời của các Reel đang theo dõi; rê chuột lên từng chỉ số để xem số Reel có dữ liệu.">
          Tổng tích lũy
        </span>
      </div>
      <div className="page-card-footer">
        <span
          className="page-card-source"
          title={`System User: ${sources || "Chưa có nguồn"}`}
        >
          <KeyRound size={13} />
          <span>{sources || "Chưa có nguồn"}</span>
        </span>
        <div className="page-card-actions">
          <button
            className="icon-button"
            onClick={onSelect}
            aria-label={`Quản lý ${page.name}`}
            title="Quản lý Page"
          >
            <MoreHorizontal size={17} />
          </button>
          {page.link && (
            <a href={page.link} target="_blank" rel="noreferrer">
              Xem Page
              <ArrowUpRight size={13} />
            </a>
          )}
        </div>
      </div>
    </article>
  );
}

function Pages({ user }: { user: User }) {
  const [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [pageSize, setPageSize] = useState(12),
    [removed, setRemoved] = useState(false),
    [selected, setSelected] = useState<Page>(),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const client = useQueryClient();
  const query = useData<{ items: Page[]; total: number }>(
    user,
    `/api/pages?limit=${pageSize}&offset=${offset}&search=${encodeURIComponent(search)}&removed=${removed}`,
  );
  async function update(p: Page, value: unknown) {
    setBusy(true);
    try {
      await api(`/api/pages/${p.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          revision: p.management_revision,
          ...(value as object),
        }),
      });
      setSelected(undefined);
      await client.invalidateQueries({ queryKey: [user.id] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="toolbar pages-toolbar">
        <SearchBox
          value={search}
          onChange={(v) => {
            setSearch(v);
            setOffset(0);
          }}
          placeholder="Tìm tên hoặc ID Page…"
        />
        <div className="toolbar-actions">
          <select
            aria-label="Số Page mỗi trang"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setOffset(0);
            }}
          >
            <option value={12}>12 / trang</option>
            <option value={24}>24 / trang</option>
            <option value={48}>48 / trang</option>
          </select>
          <div className="segmented">
            <button
              className={!removed ? "selected" : ""}
              onClick={() => {
                setRemoved(false);
                setOffset(0);
              }}
            >
              Đang quản lý
            </button>
            <button
              className={removed ? "selected" : ""}
              onClick={() => {
                setRemoved(true);
                setOffset(0);
              }}
            >
              Đã gỡ
            </button>
          </div>
        </div>
      </div>
      {error != null && <ErrorBox error={error} />}{" "}
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} retry={() => query.refetch()} />
      ) : query.data.items.length ? (
        <>
          <div className="pages-grid">
            {query.data.items.map((page) => (
              <PageCard
                key={page.id}
                page={page}
                onSelect={() => setSelected(page)}
              />
            ))}
          </div>
          <Pager
            total={query.data.total}
            offset={offset}
            setOffset={(next) => {
              setOffset(next);
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            limit={pageSize}
          />
        </>
      ) : (
        <Empty
          title={
            search
              ? "Không tìm thấy Page"
              : removed
                ? "Chưa có Page đã gỡ"
                : "Kho Page đang trống"
          }
          description={
            search
              ? "Thử tìm bằng tên hoặc ID Page khác."
              : removed
                ? "Các Page đã gỡ có thể được khôi phục tại đây."
                : "Vào Kết nối, thêm token System User và đồng bộ Pages để bắt đầu."
          }
        />
      )}{" "}
      {selected && (
        <Modal title={selected.name} onClose={() => setSelected(undefined)}>
          <div className="detail-summary">
            <Avatar page={selected} />
            <div>
              <strong>{selected.name}</strong>
              <small>Meta Page ID: {selected.id}</small>
            </div>
            <a
              className="button"
              href={selected.link}
              target="_blank"
              rel="noreferrer"
            >
              Mở Page
              <ArrowUpRight size={14} />
            </a>
          </div>
          <dl>
            <dt>Kết nối</dt>
            <dd>
              {selected.connections.map((c) => c.label).join(", ") ||
                "Chưa có nguồn"}
            </dd>
            <dt>Tình trạng đăng</dt>
            <dd>
              {selected.can_publish
                ? "Sẵn sàng"
                : "Chưa xác nhận chuẩn bị Page"}
            </dd>
          </dl>
          <p className="hint">
            Xác nhận đã chuẩn bị khi bạn đã kiểm tra thông tin Page. Đây là
            trạng thái quản lý nội bộ, không thay đổi thông tin trên Facebook.
          </p>
          {error != null && <ErrorBox error={error} />}
          <div className="modal-footer wrap">
            <button
              disabled={busy}
              onClick={() => update(selected, { removed: !removed })}
            >
              {removed ? "Khôi phục Page" : "Gỡ khỏi kho"}
            </button>
            {!removed && (
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  update(selected, {
                    information_status: selected.can_publish
                      ? "not_updated"
                      : "updated",
                  })
                }
              >
                {selected.can_publish
                  ? "Tạm khóa đăng"
                  : "Xác nhận đã chuẩn bị"}
              </button>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

function Library({
  user,
  onCreate,
}: {
  user: User;
  onCreate: (asset?: Asset) => void;
}) {
  const [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [progress, setProgress] = useState<number | null>(null),
    [error, setError] = useState<unknown>();
  const client = useQueryClient(),
    input = useRef<HTMLInputElement>(null);
  const query = useData<{ assets: Asset[]; total: number }>(
    user,
    `/api/reels/assets?limit=12&offset=${offset}&search=${encodeURIComponent(search)}`,
  );
  return (
    <>
      <div className="toolbar">
        <SearchBox
          value={search}
          onChange={(v) => {
            setSearch(v);
            setOffset(0);
          }}
          placeholder="Tìm video trong kho…"
        />
        <input
          ref={input}
          type="file"
          accept=".mp4,.mov,.m4v"
          className="sr-only"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            if (file.size > 1024 ** 3) {
              setError(new Error("Video vượt giới hạn 1 GiB."));
              return;
            }
            setError(undefined);
            setProgress(0);
            try {
              await upload(file, setProgress);
              await client.invalidateQueries({ queryKey: [user.id] });
            } catch (e) {
              setError(e);
            } finally {
              setProgress(null);
              if (input.current) input.current.value = "";
            }
          }}
        />
        <button
          className="primary"
          disabled={progress !== null}
          onClick={() => input.current?.click()}
        >
          <Upload size={16} />
          {progress !== null ? `Đang tải ${progress}%` : "Tải video lên"}
        </button>
      </div>
      <div className="hint">
        MP4, MOV, M4V · tối đa 1 GiB/tệp · Tự nhận diện video đã tải lên.
      </div>
      {progress !== null && (
        <div
          className="upload-progress"
          role="progressbar"
          aria-label="Tải video"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div style={{ width: `${progress}%` }} />
          <span>
            {progress === 100
              ? "Đang kiểm tra và lưu video…"
              : `Đã tải ${progress}%`}
          </span>
        </div>
      )}
      {error != null && <ErrorBox error={error} />}{" "}
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : query.data.assets.length ? (
        <>
          <div className="library-grid">
            {query.data.assets.map((a) => (
              <article className="asset-card" key={a.id}>
                <video
                  src={a.preview_url}
                  controls
                  preload="none"
                  aria-label={a.name}
                />
                <div>
                  <strong>{a.name}</strong>
                  <small>
                    {size(a.size)} · {date(a.created_at)}
                  </small>
                  <button onClick={() => onCreate(a)}>
                    <Plus size={14} />
                    Đặt lịch Reel
                  </button>
                </div>
              </article>
            ))}
          </div>
          <Pager
            total={query.data.total}
            offset={offset}
            setOffset={setOffset}
            limit={12}
          />
        </>
      ) : (
        <Empty
          icon={Clapperboard}
          title="Chưa có video"
          description="Tải video lên để đăng ngay hoặc đặt lịch Reel."
          action={
            <button
              onClick={() => input.current?.click()}
              disabled={progress !== null}
            >
              <Upload size={15} />
              Tải video đầu tiên
            </button>
          }
        />
      )}
    </>
  );
}

function JobDetail({
  user,
  job,
  onClose,
}: {
  user: User;
  job: Job;
  onClose: () => void;
}) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState(false);
  const query = useData<{ job: Job }>(user, `/api/reels/${job.id}`, true),
    current = query.data?.job || job;
  const client = useQueryClient();
  async function act(action: string) {
    setBusy(true);
    try {
      await post(`/api/reels/${current.id}/${action}`);
      await client.invalidateQueries({ queryKey: [user.id] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={`Lịch Reel #${current.id}`} onClose={onClose}>
      <div className="detail-summary">
        <div>
          <strong>{current.page_name}</strong>
          <small>{current.page_id}</small>
        </div>
        <Badge status={current.status} />
      </div>
      {editing && (
        <form
          className="amend-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            const f = Object.fromEntries(new FormData(e.currentTarget));
            try {
              await api(`/api/reels/${current.id}`, {
                method: "PATCH",
                body: JSON.stringify({
                  ...f,
                  expected_updated_at: current.updated_at,
                }),
              });
              await client.invalidateQueries({ queryKey: [user.id] });
              setEditing(false);
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Caption
            <textarea
              name="caption"
              defaultValue={current.caption}
              maxLength={2200}
            />
          </label>
          <label>
            Thời gian · {current.timezone}
            <input
              name="scheduled_local"
              type="datetime-local"
              defaultValue={current.scheduled_local.slice(0, 16)}
              required
            />
          </label>
          <input type="hidden" name="timezone" value={current.timezone} />
          <button className="primary" disabled={busy}>
            Lưu lịch
          </button>
        </form>
      )}
      <div className="caption-preview">
        {current.caption || "Không có caption"}
      </div>
      <dl>
        <dt>Video</dt>
        <dd>{current.asset_name}</dd>
        <dt>Nguồn</dt>
        <dd>{current.connection_label}</dd>
        <dt>Lịch địa phương</dt>
        <dd>
          {current.scheduled_local.replace("T", " ")} · {current.timezone}
        </dd>
        <dt>Mã yêu cầu</dt>
        <dd className="mono">{current.request_id}</dd>
        {current.video_id && (
          <>
            <dt>Meta Video ID</dt>
            <dd>{current.video_id}</dd>
          </>
        )}
      </dl>
      <div className="hint">
        <Clock size={16} />
        {current.message}
      </div>
      {error != null && <ErrorBox error={error} />}
      <div className="modal-footer wrap">
        {current.status === "scheduled" && (
          <button disabled={busy} onClick={() => setEditing(!editing)}>
            {editing ? "Đóng chỉnh sửa" : "Sửa lịch"}
          </button>
        )}
        {current.published_url && (
          <a
            href={current.published_url}
            target="_blank"
            rel="noreferrer"
            className="button"
          >
            Mở Reel
            <ArrowUpRight size={14} />
          </a>
        )}
        {current.can_cancel && (
          <button disabled={busy} onClick={() => act("cancel")}>
            Hủy lịch
          </button>
        )}
        {current.can_resume && (
          <button disabled={busy} onClick={() => act("resume")}>
            Tiếp tục
          </button>
        )}
        {current.can_verify && (
          <button
            className="primary"
            disabled={busy}
            onClick={() => act("verify")}
          >
            Xác minh trạng thái
          </button>
        )}
      </div>
    </Modal>
  );
}

function Calendar({ user }: { user: User }) {
  const today = localDate(new Date(), user.timezone).slice(0, 10);
  const [mode, setMode] = useState<"list" | "week" | "month">("month"),
    [week, setWeek] = useState(0),
    [month, setMonth] = useState(() => today.slice(0, 7)),
    [status, setStatus] = useState("all"),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<Job>();
  const limit = mode === "list" ? 25 : 100;
  const query = useData<{ jobs: Job[]; total: number }>(
    user,
    `/api/reels?limit=${limit}&offset=${offset}&calendar=${month}&status=${status}&sort=scheduled_asc`,
    true,
  );
  function shift(n: number) {
    const d = new Date(month + "-01T12:00:00");
    d.setMonth(d.getMonth() + n);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
    setOffset(0);
  }
  const first = new Date(month + "-01T12:00:00");
  const start = new Date(first);
  start.setDate(
    1 - ((first.getDay() + 6) % 7) + (mode === "week" ? week * 7 : 0),
  );
  const days = Array.from({ length: mode === "week" ? 7 : 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d;
  });
  return (
    <>
      <div className="toolbar">
        <div className="date-switcher">
          <button
            className="icon-button"
            aria-label="Tháng trước"
            onClick={() => shift(-1)}
          >
            <ChevronLeft size={17} />
          </button>
          <input
            type="month"
            aria-label="Chọn tháng lịch"
            value={month}
            onChange={(e) => {
              setMonth(e.target.value);
              setOffset(0);
            }}
          />
          <button
            className="icon-button"
            aria-label="Tháng sau"
            onClick={() => shift(1)}
          >
            <ChevronRight size={17} />
          </button>
        </div>
        <div className="toolbar-actions">
          {mode === "week" && (
            <select
              aria-label="Tuần hiển thị"
              value={week}
              onChange={(e) => setWeek(Number(e.target.value))}
            >
              {[0, 1, 2, 3, 4, 5].map((w) => (
                <option key={w} value={w}>
                  Tuần {w + 1}
                </option>
              ))}
            </select>
          )}
          <select
            aria-label="Lọc trạng thái lịch"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="pending">Chờ / đang chạy</option>
            <option value="completed">Đã đăng</option>
            <option value="attention">Cần xử lý</option>
            <option value="cancelled">Đã hủy</option>
          </select>
          <div className="segmented">
            {(["list", "week", "month"] as const).map((m) => (
              <button
                key={m}
                className={mode === m ? "selected" : ""}
                onClick={() => {
                  setMode(m);
                  setOffset(0);
                }}
              >
                {m === "list" ? "Danh sách" : m === "week" ? "Tuần" : "Tháng"}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="hint">Ngày giờ hiển thị theo múi giờ của từng lịch.</div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} retry={() => query.refetch()} />
      ) : (
        <>
          {mode === "list" ? (
            query.data.jobs.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Page / Video</th>
                      <th>Thời gian địa phương</th>
                      <th>Trạng thái</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {query.data.jobs.map((j) => (
                      <tr key={j.id}>
                        <td>
                          {j.page_name}
                          <small>{j.asset_name}</small>
                        </td>
                        <td>
                          {j.scheduled_local.replace("T", " ")}
                          <small>{j.timezone}</small>
                        </td>
                        <td>
                          <Badge status={j.status} />
                        </td>
                        <td>
                          <button onClick={() => setSelected(j)}>
                            Chi tiết
                            <ChevronRight size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                icon={CalendarDays}
                title="Tháng này chưa có lịch"
                description="Tạo lịch Reel để bắt đầu sắp xếp nội dung của bạn."
              />
            )
          ) : (
            <div className="calendar-grid">
              {["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"].map(
                (day) => (
                  <div className="calendar-weekday" key={day}>
                    {day}
                  </div>
                ),
              )}
              {days.map((day) => {
                const key = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
                const items = query.data.jobs.filter((j) =>
                  j.scheduled_local.startsWith(key),
                );
                return (
                  <div
                    className={`calendar-day ${key.slice(0, 7) !== month ? "outside" : ""} ${key === today ? "today" : ""}`}
                    key={key}
                  >
                    <span>{day.getDate()}</span>
                    {items.map((j) => (
                      <button
                        className={`calendar-job ${j.status === "needs_review" || j.status === "needs_user" ? "attention" : ""}`}
                        key={j.id}
                        onClick={() => setSelected(j)}
                      >
                        <strong>{j.scheduled_local.slice(11, 16)}</strong>
                        {j.page_name}
                        <small>{statusNames[j.status] || j.status}</small>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
          <Pager
            total={query.data.total}
            offset={offset}
            setOffset={setOffset}
            limit={limit}
          />
        </>
      )}
      {selected && (
        <JobDetail
          user={user}
          job={selected}
          onClose={() => setSelected(undefined)}
        />
      )}
    </>
  );
}

function AnalyticsView({ user }: { user: User }) {
  const [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const query = useData<Analytics>(
    user,
    `/api/analytics?limit=25&offset=${offset}&search=${encodeURIComponent(search)}`,
    true,
  );
  const client = useQueryClient();
  return (
    <>
      <SyncLine
        sync={query.data?.sync}
        busy={busy}
        onSync={async () => {
          setBusy(true);
          try {
            await post("/api/analytics/sync");
            await client.invalidateQueries({ queryKey: [user.id] });
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      />
      <div className="toolbar">
        <SearchBox
          value={search}
          onChange={(v) => {
            setSearch(v);
            setOffset(0);
          }}
          placeholder="Tìm nội dung hoặc Page…"
        />
        <span className="muted">Lượt phát gồm phát lại · Tổng tích lũy</span>
      </div>
      <div className="hint">
        <AlertTriangle size={16} />
        Dấu — nghĩa là chưa đọc được chỉ số. Bình luận và chia sẻ chỉ hiển thị
        khi Meta trả về số liệu riêng.
      </div>
      {error != null && <ErrorBox error={error} />}{" "}
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : (
        <>
          {query.data.items.length ? (
            <ReelTable user={user} items={query.data.items} />
          ) : (
            <Empty
              icon={ChartNoAxesCombined}
              title="Chưa có thống kê phù hợp"
              description="Đồng bộ Page và kiểm tra quyền đọc thống kê của System User."
            />
          )}
          <Pager
            total={query.data.total}
            offset={offset}
            setOffset={setOffset}
          />
          <p className="footnote">
            {query.data.coverage_note}
            {query.data.discovery.some((d) => d.status === "partial")
              ? " Một số Page còn nội dung cũ; lượt đồng bộ tiếp theo sẽ tiếp tục."
              : ""}
          </p>
        </>
      )}
    </>
  );
}

function PasswordForm({
  user,
  onUser,
  required = false,
}: {
  user: User;
  onUser: (u: User) => void;
  required?: boolean;
}) {
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  return (
    <form
      className="settings-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        if (form.get("new_password") !== form.get("confirm_password")) {
          setError(new Error("Mật khẩu xác nhận chưa khớp."));
          return;
        }
        setBusy(true);
        try {
          const result = await post<{ user: User }>("/api/auth/password", {
            old_password: form.get("old_password"),
            new_password: form.get("new_password"),
          });
          onUser(result.user);
          setError(
            new Error(
              "Đã đổi mật khẩu. Các phiên và MCP token cũ đã được thu hồi.",
            ),
          );
          (e.target as HTMLFormElement).reset();
        } catch (e) {
          setError(e);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>
        {required ? "Đặt mật khẩu riêng trước khi bắt đầu" : "Đổi mật khẩu"}
      </h3>
      <p>Tài khoản {user.username} · tối thiểu 12 ký tự</p>
      <label>
        Mật khẩu hiện tại
        <input
          name="old_password"
          type="password"
          autoComplete="current-password"
          required
        />
      </label>
      <label>
        Mật khẩu mới
        <input
          name="new_password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          maxLength={1024}
        />
      </label>
      <label>
        Xác nhận mật khẩu mới
        <input
          name="confirm_password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          maxLength={1024}
        />
      </label>
      {error != null && <ErrorBox error={error} />}
      <button className="primary" disabled={busy}>
        Lưu mật khẩu
        <Check size={15} />
      </button>
    </form>
  );
}

function Activity({ user }: { user: User }) {
  const [offset, setOffset] = useState(0);
  const query = useData<{
    items: {
      id: number;
      action: string;
      status: string;
      message: string;
      created_at: string;
      connection_label: string | null;
    }[];
    total: number;
  }>(user, `/api/events?limit=25&offset=${offset}`, true);
  return (
    <>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Hoạt động</th>
                  <th>Nguồn</th>
                  <th>Kết quả</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((e) => (
                  <tr key={e.id}>
                    <td>{date(e.created_at)}</td>
                    <td>
                      {e.message}
                      <small>{e.action}</small>
                    </td>
                    <td>{e.connection_label || "—"}</td>
                    <td>
                      <Badge
                        status={e.status === "ok" ? "completed" : e.status}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!query.data.items.length && (
              <Empty
                title="Chưa có hoạt động"
                description="Nhật ký sẽ ghi nhận các thao tác trong kho của bạn."
              />
            )}
          </div>
          <Pager
            total={query.data.total}
            offset={offset}
            setOffset={setOffset}
          />
        </>
      )}
    </>
  );
}
function Settings({ user, onUser }: { user: User; onUser: (u: User) => void }) {
  const [tab, setTab] = useState("mcp"),
    [mcpClient, setMcpClient] = useState<"codex" | "claude">("codex"),
    [creating, setCreating] = useState(false),
    [token, setToken] = useState<string>(),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const client = useQueryClient();
  const query = useData<{
    mcp_url: string;
    items: {
      id: string;
      label: string;
      can_write: boolean;
      expires_at: string;
      revoked_at: string | null;
    }[];
  }>(user, "/api/account/mcp-tokens");
  const mcpUrl = query.data?.mcp_url || `${location.origin}/mcp`;
  const localEndpoint =
    /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?\//i.test(mcpUrl);
  const clientConfig =
    mcpClient === "codex"
      ? `[mcp_servers.pagemanager]\nurl = ${JSON.stringify(mcpUrl)}\nbearer_token_env_var = "PAGEMANAGER_MCP_TOKEN"\ndefault_tools_approval_mode = "approve"\n`
      : JSON.stringify(
          {
            mcpServers: {
              pagemanager: {
                type: "http",
                url: mcpUrl,
                headers: { Authorization: "Bearer ${PAGEMANAGER_MCP_TOKEN}" },
              },
            },
          },
          null,
          2,
        );
  const claudePermissions = JSON.stringify(
    { permissions: { allow: ["mcp__pagemanager__*"] } },
    null,
    2,
  );
  return (
    <>
      <div className="segmented settings-tabs">
        <button
          className={tab === "mcp" ? "selected" : ""}
          onClick={() => setTab("mcp")}
        >
          Codex & Claude
        </button>
        <button
          className={tab === "password" ? "selected" : ""}
          onClick={() => setTab("password")}
        >
          Mật khẩu
        </button>
        <button
          className={tab === "activity" ? "selected" : ""}
          onClick={() => setTab("activity")}
        >
          Hoạt động
        </button>
      </div>
      {tab === "activity" ? (
        <Activity user={user} />
      ) : tab === "password" ? (
        <PasswordForm user={user} onUser={onUser} />
      ) : (
        <>
          <div className="section-heading">
            <div>
              <h3>Kết nối Codex và Claude</h3>
              <p>Toàn quyền Page, System User và Reel trong kho của bạn.</p>
            </div>
            <button className="primary" onClick={() => setCreating(true)}>
              <Plus size={15} />
              Tạo MCP token
            </button>
          </div>
          <details className="mcp-connect-guide">
            <summary>
              Kết nối từ máy khác
              <ChevronRight size={16} />
            </summary>
            <div className="mcp-guide-content">
              {localEndpoint && (
                <p className="mcp-local-note">
                  URL hiện tại chỉ dùng trên máy chủ. Để kết nối từ máy khác,
                  máy chủ cần URL HTTPS truy cập được và cấu hình
                  PM_PUBLIC_ORIGIN theo URL đó.
                </p>
              )}
              <div className="mcp-guide-heading">
                <div className="segmented">
                  <button
                    className={mcpClient === "codex" ? "selected" : ""}
                    onClick={() => setMcpClient("codex")}
                  >
                    Codex
                  </button>
                  <button
                    className={mcpClient === "claude" ? "selected" : ""}
                    onClick={() => setMcpClient("claude")}
                  >
                    Claude Code
                  </button>
                </div>
                <button
                  onClick={() =>
                    navigator.clipboard.writeText(clientConfig).catch(setError)
                  }
                >
                  <Copy size={14} />
                  Sao chép cấu hình
                </button>
              </div>
              <p>
                Trên máy kết nối, đặt MCP token cá nhân vào biến môi trường{" "}
                <code>PAGEMANAGER_MCP_TOKEN</code>, rồi khởi động lại ứng dụng.
              </p>
              <small>
                {mcpClient === "codex"
                  ? ".codex/config.toml"
                  : ".mcp.json trong thư mục dự án"}
              </small>
              <pre>{clientConfig}</pre>
              {mcpClient === "claude" && (
                <>
                  <small>
                    Cho phép các công cụ PageManager trong
                    .claude/settings.local.json
                  </small>
                  <pre>{claudePermissions}</pre>
                </>
              )}
              <p>
                Cấu hình chỉ cấp quyền cho MCP PageManager. Token mới mặc định
                có đầy đủ quyền trong kho của bạn.
              </p>
            </div>
          </details>
          <div className="endpoint">
            <code>{query.data?.mcp_url || `${location.origin}/mcp`}</code>
            <button
              className="icon-button"
              aria-label="Sao chép URL MCP"
              onClick={() =>
                navigator.clipboard
                  .writeText(query.data?.mcp_url || `${location.origin}/mcp`)
                  .catch((e) => setError(e))
              }
            >
              <Copy size={15} />
            </button>
          </div>
          {error != null && <ErrorBox error={error} />}{" "}
          {query.isPending ? (
            <Loading />
          ) : query.error ? (
            <ErrorBox error={query.error} />
          ) : query.data.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Tên</th>
                    <th>Quyền</th>
                    <th>Hết hạn</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {query.data.items.map((t) => (
                    <tr key={t.id}>
                      <td>
                        {t.label}
                        {t.revoked_at && <small>Đã thu hồi</small>}
                      </td>
                      <td>
                        {t.can_write ? "Toàn quyền trong kho" : "Chỉ đọc"}
                      </td>
                      <td>{date(t.expires_at)}</td>
                      <td>
                        {!t.revoked_at && !t.can_write && (
                          <button
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                await api(`/api/account/mcp-tokens/${t.id}`, {
                                  method: "PATCH",
                                  body: JSON.stringify({ can_write: true }),
                                });
                                await client.invalidateQueries({
                                  queryKey: [user.id],
                                });
                              } catch (e) {
                                setError(e);
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            Cấp toàn quyền
                          </button>
                        )}
                        {!t.revoked_at && (
                          <button
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                await api(`/api/account/mcp-tokens/${t.id}`, {
                                  method: "DELETE",
                                });
                                await client.invalidateQueries({
                                  queryKey: [user.id],
                                });
                              } catch (e) {
                                setError(e);
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            Thu hồi
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              icon={KeyRound}
              title="Chưa có MCP token"
              description="Tạo token để kết nối Codex hoặc Claude trên máy này và máy khác."
            />
          )}
        </>
      )}
      {creating && (
        <Modal
          title={token ? "MCP token đã tạo" : "Tạo MCP token"}
          onClose={() => {
            setCreating(false);
            setToken(undefined);
          }}
        >
          {token ? (
            <>
              <p>
                Token chỉ hiển thị trong lần này. Lưu vào trình quản lý bí mật
                hoặc cấu hình MCP cá nhân.
              </p>
              <div className="token-result">
                <code>{token}</code>
                <button
                  onClick={() =>
                    navigator.clipboard
                      .writeText(token)
                      .catch((e) => setError(e))
                  }
                >
                  <Copy size={15} />
                  Sao chép
                </button>
              </div>
              <div className="modal-footer">
                <button
                  className="primary"
                  onClick={() => {
                    setCreating(false);
                    setToken(undefined);
                  }}
                >
                  Đã lưu
                </button>
              </div>
            </>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                const f = new FormData(e.currentTarget);
                try {
                  const r = await post("/api/account/mcp-tokens", {
                    label: f.get("label"),
                    days: Number(f.get("days")),
                    can_write: f.get("can_write") === "on",
                  });
                  setToken(r.token);
                  await client.invalidateQueries({ queryKey: [user.id] });
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label>
                Tên kết nối
                <input
                  name="label"
                  placeholder="Codex / Claude trên máy khác"
                  required
                  maxLength={100}
                />
              </label>
              <label>
                Hiệu lực
                <select name="days">
                  <option value="30">30 ngày</option>
                  <option value="7">7 ngày</option>
                  <option value="90">90 ngày</option>
                </select>
              </label>
              <label className="checkbox">
                <input type="checkbox" name="can_write" defaultChecked />
                Toàn quyền Page, System User, video và đăng/đặt lịch Reel
              </label>
              <p className="hint">
                Mặc định đầy đủ quyền trong kho của bạn. Token Meta đã lưu không
                được trả lại cho máy kết nối.
              </p>
              {error != null && <ErrorBox error={error} />}
              <div className="modal-footer">
                <button type="button" onClick={() => setCreating(false)}>
                  Hủy
                </button>
                <button className="primary" disabled={busy}>
                  Tạo token
                </button>
              </div>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}

function UsersView({ user }: { user: User }) {
  const query = useData<{
    items: (User & { active: boolean })[];
    max_users: number;
  }>(user, "/api/admin/users");
  const client = useQueryClient();
  const [target, setTarget] = useState<User & { active: boolean }>(),
    [temporary, setTemporary] = useState<string>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  return (
    <>
      <div className="hint">
        <Users size={16} />
        {query.data?.items.length || 0}/20 tài khoản · Mỗi người dùng có kho
        Page và token riêng.
      </div>
      {query.isPending ? (
        <Loading />
      ) : query.error ? (
        <ErrorBox error={query.error} />
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Người dùng</th>
                <th>Vai trò</th>
                <th>Tình trạng</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.username}
                    {u.id === user.id && <small>Tài khoản của bạn</small>}
                  </td>
                  <td>{u.role === "admin" ? "Quản trị viên" : "Chủ kho"}</td>
                  <td>
                    <Badge status={u.active ? "active" : "disconnected"} />
                    {u.must_change && <small>Cần đổi mật khẩu ban đầu</small>}
                  </td>
                  <td>
                    <button onClick={() => setTarget(u)}>
                      Quản lý
                      <ChevronRight size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {target && (
        <Modal
          title={`Quản lý ${target.username}`}
          onClose={() => {
            setTarget(undefined);
            setTemporary(undefined);
            setError(undefined);
          }}
        >
          {temporary ? (
            <div className="token-result">
              <p>Mật khẩu tạm · yêu cầu đổi khi đăng nhập</p>
              <code>{temporary}</code>
              <button
                onClick={() =>
                  navigator.clipboard
                    .writeText(temporary)
                    .catch((e) => setError(e))
                }
              >
                <Copy size={15} />
                Sao chép
              </button>
            </div>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const f = new FormData(e.currentTarget);
                setBusy(true);
                try {
                  const r = await api(`/api/admin/users/${target.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({
                      username: f.get("username"),
                      role: f.get("role"),
                      active: f.get("active") === "on",
                      reset_password: f.get("reset_password") === "on",
                    }),
                  });
                  await client.invalidateQueries({ queryKey: [user.id] });
                  if (r.temporary_password) setTemporary(r.temporary_password);
                  else setTarget(undefined);
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <label>
                Tên đăng nhập
                <input
                  name="username"
                  required
                  pattern="[a-z0-9_-]{3,32}"
                  defaultValue={target.username}
                />
              </label>
              <label>
                Vai trò
                <select name="role" defaultValue={target.role}>
                  <option value="owner">Chủ kho</option>
                  <option value="admin">Quản trị viên</option>
                </select>
              </label>
              <label className="checkbox">
                <input
                  name="active"
                  type="checkbox"
                  defaultChecked={target.active}
                />
                Cho phép đăng nhập và chạy tác vụ
              </label>
              {target.id !== user.id && (
                <label className="checkbox">
                  <input name="reset_password" type="checkbox" />
                  Cấp mật khẩu tạm mới
                </label>
              )}
              <p className="hint">
                Lưu thay đổi sẽ thu hồi phiên đăng nhập và MCP token của tài
                khoản này.
              </p>
              {error != null && <ErrorBox error={error} />}
              <div className="modal-footer">
                <button type="button" onClick={() => setTarget(undefined)}>
                  Hủy
                </button>
                <button className="primary" disabled={busy}>
                  Lưu thay đổi
                </button>
              </div>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}

function ResourcePicker<T extends { id: string }>(props: {
  user: User;
  kind: "pages" | "assets";
  value: T | undefined;
  onChange: (value: T) => void;
  label: string;
}) {
  const { user, kind, value, onChange, label } = props;
  const [open, setOpen] = useState(false),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0);
  const path = kind === "pages" ? "/api/pages" : "/api/reels/assets";
  const query = useData<{ items?: Page[]; assets?: Asset[]; total: number }>(
    user,
    `${path}?limit=25&offset=${offset}&search=${encodeURIComponent(search)}`,
  );
  const rows = (query.data?.items ||
    query.data?.assets ||
    []) as unknown as T[];
  return (
    <div className="resource-picker">
      <label>{label}</label>
      <button
        type="button"
        className="picker-trigger"
        onClick={() => setOpen(!open)}
      >
        {value
          ? (value as any).name
          : `Chọn ${kind === "pages" ? "Page" : "video"} trong kho`}
        <ChevronRight size={15} />
      </button>
      {open && (
        <div className="picker-menu">
          <SearchBox
            value={search}
            onChange={(v) => {
              setSearch(v);
              setOffset(0);
            }}
            placeholder={kind === "pages" ? "Tìm Page…" : "Tìm video…"}
          />
          {query.isPending ? (
            <Loading />
          ) : query.error ? (
            <ErrorBox error={query.error} />
          ) : rows.length ? (
            rows.map((row) => {
              const p = row as unknown as Page;
              return (
                <button
                  className="picker-option"
                  key={row.id}
                  type="button"
                  disabled={kind === "pages" && !p.can_publish}
                  onClick={() => {
                    onChange(row);
                    setOpen(false);
                  }}
                >
                  <span>
                    {(row as any).name}
                    <small>
                      {kind === "pages"
                        ? p.can_publish
                          ? p.id
                          : "Cần xác nhận chuẩn bị Page"
                        : `${size((row as unknown as Asset).size)}`}
                    </small>
                  </span>
                  {value?.id === row.id && <Check size={14} />}
                </button>
              );
            })
          ) : (
            <p className="muted">Chưa có mục phù hợp.</p>
          )}
          <Pager
            total={query.data?.total || 0}
            offset={offset}
            setOffset={setOffset}
          />
        </div>
      )}
    </div>
  );
}

function localDate(instant: Date, zone: string) {
  const p = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(instant);
  const get = (type: string) => p.find((v) => v.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}
function Composer({
  user,
  initialAsset,
  onClose,
  onCreated,
}: {
  user: User;
  initialAsset?: Asset;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [page, setPage] = useState<Page>(),
    [asset, setAsset] = useState<Asset | undefined>(initialAsset),
    [source, setSource] = useState(""),
    [caption, setCaption] = useState(""),
    [zone, setZone] = useState(user.timezone),
    [scheduled, setScheduled] = useState(() =>
      localDate(new Date(Date.now() + 600000), user.timezone),
    ),
    [fold, setFold] = useState(""),
    [now, setNow] = useState(false),
    [review, setReview] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  const submitted = useRef<{ path: string; value: object } | undefined>(
    undefined,
  );
  const id = useRef(crypto.randomUUID());
  const sources =
    page?.connections.filter((c) =>
      ["working", "unchecked"].includes(c.status),
    ) || [];
  async function submit() {
    if (!page || !asset) return;
    setBusy(true);
    setError(undefined);
    if (!submitted.current) {
      const value = {
        request_id: id.current,
        page_id: page.id,
        connection_id: Number(source),
        asset_id: asset.id,
        caption,
        timezone: zone,
        approval_policy: null,
        ...(!now
          ? {
              scheduled_local: scheduled,
              ...(fold !== "" ? { fold: Number(fold) } : {}),
            }
          : {}),
      };
      submitted.current = {
        path: now ? "/api/reels/now" : "/api/reels",
        value,
      };
    }
    try {
      await post(submitted.current.path, submitted.current.value);
      onCreated();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={review ? "Xem lại lịch Reel" : "Tạo lịch Reel"}
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      {review ? (
        <>
          <div className="review-target">
            <ShieldCheck size={21} />
            <div>
              <strong>{page?.name}</strong>
              <small>
                Page ID: {page?.id} ·{" "}
                {sources.find((c) => String(c.id) === source)?.label}
              </small>
            </div>
          </div>
          {asset && (
            <video
              className="review-video"
              src={asset.preview_url}
              controls
              preload="metadata"
            />
          )}
          <div className="caption-preview">{caption || "Không có caption"}</div>
          <dl>
            <dt>Thời điểm</dt>
            <dd>
              {now ? "Đăng ngay sau khi xác nhận" : scheduled.replace("T", " ")}
            </dd>
            <dt>Múi giờ</dt>
            <dd>{zone}</dd>
            <dt>Hiển thị</dt>
            <dd>Công khai trên Page đã chọn</dd>
            <dt>Mã yêu cầu</dt>
            <dd className="mono">{id.current}</dd>
          </dl>
          {error != null && (
            <>
              <ErrorBox error={error} />
              <p className="hint">
                Nếu mất phản hồi, gửi lại cùng yêu cầu sẽ kiểm tra lịch đã lưu.
                Nội dung yêu cầu được giữ nguyên.
              </p>
            </>
          )}
          <div className="modal-footer">
            <button
              disabled={busy || !!submitted.current}
              onClick={() => setReview(false)}
            >
              Chỉnh sửa
            </button>
            <button className="primary" disabled={busy} onClick={submit}>
              {busy ? (
                <LoaderCircle size={16} className="spin" />
              ) : (
                <Check size={16} />
              )}{" "}
              {submitted.current
                ? "Gửi lại cùng yêu cầu"
                : now
                  ? "Xác nhận đăng ngay"
                  : "Xác nhận đặt lịch"}
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!page || !asset || !source) {
              setError(new Error("Chọn Page, nguồn token và video."));
              return;
            }
            setError(undefined);
            setReview(true);
          }}
        >
          <ResourcePicker<Page>
            user={user}
            kind="pages"
            value={page}
            onChange={(p) => {
              setPage(p);
              const active = p.connections.filter((c) =>
                ["working", "unchecked"].includes(c.status),
              );
              setSource(active.length === 1 ? String(active[0].id) : "");
            }}
            label="Page sẽ đăng"
          />
          {page && (
            <label>
              Nguồn System User
              <select
                required
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">Chọn nguồn kết nối</option>
                {sources.map((c) => (
                  <option value={c.id} key={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <ResourcePicker<Asset>
            user={user}
            kind="assets"
            value={asset}
            onChange={setAsset}
            label="Video"
          />
          <label>
            Caption
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              maxLength={2200}
              rows={4}
              placeholder="Viết điều bạn muốn chia sẻ…"
            />
            <small className="align-end">{caption.length}/2.200</small>
          </label>
          <div className="segmented">
            <button
              type="button"
              className={!now ? "selected" : ""}
              onClick={() => setNow(false)}
            >
              <CalendarDays size={14} />
              Đặt lịch
            </button>
            <button
              type="button"
              className={now ? "selected" : ""}
              onClick={() => setNow(true)}
            >
              <Play size={14} />
              Đăng ngay
            </button>
          </div>
          <div className="form-grid">
            {!now && (
              <label>
                Ngày giờ địa phương
                <input
                  type="datetime-local"
                  required
                  value={scheduled}
                  onChange={(e) => setScheduled(e.target.value)}
                />
              </label>
            )}
            <label>
              Múi giờ
              <select value={zone} onChange={(e) => setZone(e.target.value)}>
                {[
                  ...new Set([
                    user.timezone,
                    "America/Los_Angeles",
                    "Asia/Ho_Chi_Minh",
                    "America/New_York",
                    "Europe/Berlin",
                    "UTC",
                  ]),
                ].map((z) => (
                  <option key={z}>{z}</option>
                ))}
              </select>
            </label>
          </div>
          {!now && (
            <details>
              <summary>Giờ lặp khi chuyển giờ mùa hè</summary>
              <label>
                Lần xuất hiện
                <select value={fold} onChange={(e) => setFold(e.target.value)}>
                  <option value="">Tự kiểm tra; hỏi lại nếu giờ lặp</option>
                  <option value="0">Lần đầu</option>
                  <option value="1">Lần sau</option>
                </select>
              </label>
            </details>
          )}
          {error != null && <ErrorBox error={error} />}
          <div className="modal-footer">
            <button type="button" onClick={onClose}>
              Hủy
            </button>
            <button className="primary" disabled={!page || !asset || !source}>
              Xem lại
              <ChevronRight size={16} />
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null),
    [boot, setBoot] = useState(true),
    [view, setView] = useState(() => location.hash.slice(1) || "overview"),
    [composer, setComposer] = useState<{ asset?: Asset } | null>(null),
    [theme, setTheme] = useState(
      () => localStorage.getItem("pm-theme") || "light",
    ),
    [logoutError, setLogoutError] = useState<unknown>();
  const client = useQueryClient();
  function onUser(next: User) {
    if (user?.id !== next.id) client.clear();
    setCsrf(next.csrf_token);
    setUser(next);
    notifySessionChange();
  }
  useEffect(() => {
    const expire = () => {
      client.clear();
      setCsrf("");
      setUser(null);
      setComposer(null);
    };
    const expired = () => {
      expire();
      notifySessionChange();
    };
    const stop = watchSessionChanges(expire);
    window.addEventListener("pm-session-expired", expired);
    return () => {
      stop();
      window.removeEventListener("pm-session-expired", expired);
    };
  }, [client]);
  useEffect(() => {
    api<{ user: User }>("/api/auth/me")
      .then((r) => {
        setCsrf(r.user.csrf_token);
        setUser(r.user);
      })
      .catch(() => {})
      .finally(() => setBoot(false));
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("pm-theme", theme);
  }, [theme]);
  useEffect(() => {
    const listener = () => setView(location.hash.slice(1) || "overview");
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  useEffect(() => {
    if (!user || user.must_change) return;
    const stream = new EventSource("/api/stream");
    stream.addEventListener("status", () => {
      client.invalidateQueries({ queryKey: [user.id, "/api/overview"] });
      client.invalidateQueries({
        queryKey: [user.id],
        predicate: (q) =>
          String(q.queryKey[1]).startsWith("/api/reels?") ||
          String(q.queryKey[1]).startsWith("/api/analytics?"),
      });
    });
    return () => stream.close();
  }, [user?.id, user?.must_change]);
  function navigate(next: string) {
    location.hash = next;
    setView(next);
  }
  async function logout() {
    try {
      await post("/api/auth/logout");
      client.clear();
      setCsrf("");
      setUser(null);
      setComposer(null);
      notifySessionChange();
    } catch (e) {
      setLogoutError(e);
    }
  }
  if (boot)
    return (
      <div className="boot">
        <Layers2 size={28} />
        <Loading />
      </div>
    );
  if (!user) return <Login onLogin={onUser} />;
  if (user.must_change)
    return (
      <div className="first-password">
        <div className="brand">
          <span>
            <Layers2 size={21} />
          </span>
          PageManager
        </div>
        <PasswordForm user={user} onUser={onUser} required />
        <button className="text-button" onClick={logout}>
          Đăng xuất
          <LogOut size={14} />
        </button>
        {logoutError != null && <ErrorBox error={logoutError} />}
      </div>
    );
  const current = view in titles ? view : "overview";
  const navigation = [
    ["overview", LayoutDashboard],
    ["pages", PanelsTopLeft],
    ["calendar", CalendarDays],
    ["library", Clapperboard],
    ["analytics", ChartNoAxesCombined],
    ["connections", KeyRound],
  ] as const;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span>
            <Layers2 size={20} />
          </span>
          PageManager
        </div>
        <div className="workspace-card">
          <span className="workspace-symbol">
            <PanelsTopLeft size={16} />
          </span>
          <div>
            <strong>Kho cá nhân</strong>
            <small>Page & nội dung của bạn</small>
          </div>
        </div>
        <nav aria-label="Điều hướng">
          {navigation.map(([id, Icon]) => (
            <button
              key={id}
              className={current === id ? "active" : ""}
              aria-current={current === id ? "page" : undefined}
              title={titles[id][0]}
              onClick={() => navigate(id)}
            >
              <Icon size={17} />
              {titles[id][0]}
              {current === id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          {user.role === "admin" && (
            <button
              className={current === "users" ? "active" : ""}
              onClick={() => navigate("users")}
            >
              <Users size={17} />
              Người dùng<span className="small-count">20</span>
            </button>
          )}
          <button
            className={current === "settings" ? "active" : ""}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={17} />
            Cài đặt
          </button>
          <div className="sidebar-account">
            <span className="owner-avatar small">
              {user.username.slice(0, 2).toUpperCase()}
            </span>
            <div>
              {user.username}
              <small>
                {user.role === "admin" ? "Quản trị viên" : "Chủ kho"}
              </small>
            </div>
            <button
              className="icon-button"
              aria-label="Đăng xuất"
              onClick={logout}
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <div>
            <span className="topbar-label">Không gian làm việc</span>
            <ChevronRight size={13} />
            <strong>{titles[current][0]}</strong>
          </div>
          <div className="topbar-actions">
            <button
              className="icon-button"
              aria-label="Chuyển giao diện sáng tối"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </button>
            <button className="primary" onClick={() => setComposer({})}>
              <Plus size={16} />
              Tạo lịch Reel
            </button>
          </div>
        </header>
        <main className="main-content">
          <div className="page-heading">
            <div>
              <h1>{titles[current][1]}</h1>
              {current === "overview" && (
                <p className="view-subtitle">
                  Hiệu quả và lịch đăng trong kho của bạn.
                </p>
              )}
            </div>
          </div>
          {logoutError != null && <ErrorBox error={logoutError} />}
          <div className="page-content" key={current}>
            {current === "overview" ? (
              <Dashboard
                user={user}
                navigate={navigate}
                onCreate={() => setComposer({})}
              />
            ) : current === "pages" ? (
              <Pages user={user} />
            ) : current === "connections" ? (
              <Connections user={user} />
            ) : current === "library" ? (
              <Library
                user={user}
                onCreate={(asset) => setComposer({ asset })}
              />
            ) : current === "calendar" ? (
              <Calendar user={user} />
            ) : current === "analytics" ? (
              <AnalyticsView user={user} />
            ) : current === "users" && user.role === "admin" ? (
              <UsersView user={user} />
            ) : (
              <Settings user={user} onUser={onUser} />
            )}
          </div>
        </main>
      </div>
      {composer && (
        <Composer
          user={user}
          initialAsset={composer.asset}
          onClose={() => setComposer(null)}
          onCreated={() => {
            setComposer(null);
            client.invalidateQueries({ queryKey: [user.id] });
            navigate("calendar");
          }}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
