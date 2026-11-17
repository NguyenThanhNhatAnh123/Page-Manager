export type User = {
  id: string;
  username: string;
  role: "admin" | "owner";
  timezone: string;
  must_change: boolean;
  csrf_token: string;
};
export type Connection = {
  id: number;
  label: string;
  token_type: string;
  app_id: string | null;
  business_id: string | null;
  status: string;
  connected: boolean;
  page_count: number;
  revision: number;
  checked_at: string | null;
  error: string | null;
  identity_name: string | null;
  has_token: boolean;
};
export type Page = {
  id: string;
  name: string;
  avatar_url: string;
  category: string;
  link: string;
  status: string;
  can_publish: boolean;
  posting_block_reason: string | null;
  management_revision: number;
  information_status: string;
  connections: { id: number; label: string; status: string }[];
  details?: { followers_count?: number; [key: string]: unknown };
  analytics?: {
    tracked: number;
    views: number | null;
    comments: number | null;
    shares: number | null;
    views_known: number;
    comments_known: number;
    shares_known: number;
  };
};
export type Asset = {
  id: string;
  name: string;
  size: number;
  mime: string;
  created_at: string;
  preview_url: string;
};
export type Job = {
  id: number;
  request_id: string;
  page_name: string;
  page_id: string;
  connection_label: string;
  connection_id: number;
  asset_name: string;
  caption: string;
  status: string;
  message: string;
  scheduled_local: string;
  scheduled_at: string;
  timezone: string;
  published_url: string | null;
  video_id: string | null;
  can_cancel: boolean;
  can_resume: boolean;
  can_verify: boolean;
  updated_at: string;
  asset?: Asset;
};
export type Reel = {
  video_id: string;
  page_id: string;
  page_name: string;
  caption: string;
  published_at: string | null;
  permalink_url: string | null;
  views: number | null;
  comments: number | null;
  shares: number | null;
  metric_status: string | null;
  observed_at: string | null;
  views_observed_at: string | null;
  comments_observed_at: string | null;
  shares_observed_at: string | null;
};
export type Sync = {
  status: string;
  finished_at: string | null;
  refreshed: number;
  unavailable: number;
  message: string | null;
};
export type Analytics = {
  items: Reel[];
  total: number;
  bands: Record<string, number>;
  totals: {
    tracked: number;
    views_known: number;
    comments_known: number;
    shares_known: number;
    views: number | null;
    comments: number | null;
    shares: number | null;
  };
  sync: Sync;
  coverage_note: string;
  discovery: { status: string }[];
};
export type Overview = {
  stats: {
    pages: number;
    connections: number;
    working_connections: number;
    needs_attention: number;
  };
  analytics: Analytics;
  scheduler: {
    scheduler_running: boolean;
    scheduler_healthy: boolean;
    active_count: number;
  };
  sync: Sync;
};
let csrf = "";
let sessionGeneration = 0;
const sessionStorageKey = "pm-session-change";
export function setCsrf(value: string) {
  sessionGeneration++;
  csrf = value;
}
export function notifySessionChange() {
  try {
    window.localStorage.setItem(sessionStorageKey, crypto.randomUUID());
  } catch {
    // Storage may be unavailable; this tab must still finish its auth action.
  }
}
export function watchSessionChanges(reset: () => void) {
  const listener = (event: StorageEvent) => {
    if (event.key === sessionStorageKey) reset();
  };
  window.addEventListener("storage", listener);
  return () => window.removeEventListener("storage", listener);
}
function requireCurrentSession(generation: number) {
  if (generation !== sessionGeneration)
    throw new ApiError(409, "Phiên đăng nhập đã thay đổi. Thao tác cũ đã được bỏ qua.");
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const generation = sessionGeneration;
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      "X-CSRF-Token": csrf,
      ...options.headers,
    },
  });
  const value = await response
    .json()
    .catch(() => ({ detail: "Phản hồi máy chủ không hợp lệ." }));
  requireCurrentSession(generation);
  if (response.status === 401 && path != "/api/auth/login")
    window.dispatchEvent(new Event("pm-session-expired"));
  if (!response.ok)
    throw new ApiError(
      response.status,
      typeof value.detail === "string"
        ? value.detail
        : "Dữ liệu chưa hợp lệ. Kiểm tra các trường nhập.",
    );
  return value;
}
export const post = <T = any>(path: string, value: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(value) });
export function upload(
  file: File,
  onProgress: (progress: number) => void,
): Promise<{ asset: Asset }> {
  const generation = sessionGeneration;
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/reels/assets");
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    request.setRequestHeader("X-CSRF-Token", csrf);
    request.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };
    request.onerror = () =>
      reject(
        new Error(
          "Mất kết nối khi tải video. Kiểm tra thư viện trước khi thử lại.",
        ),
      );
    request.onload = () => {
      try {
        requireCurrentSession(generation);
      } catch (error) {
        reject(error);
        return;
      }
      if (request.status === 401)
        window.dispatchEvent(new Event("pm-session-expired"));
      let value;
      try {
        value = JSON.parse(request.responseText);
      } catch {
        reject(new Error("Phản hồi máy chủ không hợp lệ."));
        return;
      }
      if (request.status >= 200 && request.status < 300) resolve(value);
      else
        reject(
          new ApiError(request.status, value.detail || "Chưa tải được video."),
        );
    };
    request.send(file);
  });
}
export function number(value: number | null | undefined, compact = false) {
  return value == null
    ? "—"
    : new Intl.NumberFormat(
        "vi-VN",
        compact ? { notation: "compact", maximumFractionDigits: 1 } : {},
      ).format(value);
}
export function date(value: string | null | undefined) {
  if (!value) return "Chưa cập nhật";
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
export function size(value: number) {
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(1)} GB`
    : `${(value / 1024 ** 2).toFixed(1)} MB`;
}
