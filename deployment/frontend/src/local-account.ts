// Invitation-only staff accounts for the loopback Agent, following CareFlow Atlas.
// The server owns every permission check; this module only renders the sign-in,
// password-link and settings pages and exposes the account to the renderer.

export interface Account {
  id: string;
  email: string;
  name: string;
  role: "ADMIN" | "MEMBER";
  disabled: boolean;
  pending: boolean;
  createdAt: number;
}
interface SessionView { user: Account; expiresAt: number }
interface Device { id: string; created_at: number; current: boolean }
interface Limits { messages: number | null; images: number | null; resetsAt: number }
interface OwnUsage { messages: number; images: number; limits: Limits }
type WeekUsage = { messages: number; images: number; continuations: number };
interface UsageReport { weeks: string[]; limits: Limits; usage: Record<string, Record<string, WeekUsage>> }
interface AuditEvent { id: number; time: number; action: string; actor_email?: string; target_email?: string }

export interface AccountControls { name: string; email: string; role: Account["role"]; openSettings: () => void; logout: () => Promise<void> }
declare global { interface Window { ngopilotAccount?: AccountControls } }

/** Mirrors SESSION_IDLE_SECONDS in ngopilot_gateway/local_accounts.py. */
const SESSION_IDLE_MS = 6 * 60 * 60_000;
const CHANNEL = "ngopilot-account";
const actions: Record<string, string> = {
  login: "登入", login_failed: "登入失敗", logout: "登出", user_created: "建立帳號", user_updated: "修改帳號",
  password_link_created: "產生設定密碼連結", password_set: "設定密碼", password_changed: "修改密碼",
  other_sessions_revoked: "登出其他裝置", operator_recovery: "運維恢復管理員",
};

class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method, credentials: "same-origin", cache: "no-store",
    headers: method === "GET" ? {} : { "Content-Type": "application/json" },
    body: method === "GET" ? undefined : JSON.stringify(body ?? {}),
  });
  const value = await response.json().catch(() => null) as (T & { detail?: unknown }) | null;
  if (!response.ok) {
    const detail = value?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : "帳號服務未有回應，請稍後重試。");
  }
  return value as T;
}

/** Tells other tabs to re-check the account, then reloads this one. */
function changed(): void {
  if (typeof BroadcastChannel !== "undefined") {
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage("changed");
    channel.close();
  }
  window.location.reload();
}

function h<K extends keyof HTMLElementTagNameMap>(tag: K, props: Partial<HTMLElementTagNameMap[K]> & Record<string, unknown> = {}, ...children: (Node | string | null | false)[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "role" || key.startsWith("data-") || key.startsWith("aria-")) node.setAttribute(key, String(value));
    else (node as unknown as Record<string, unknown>)[key] = value;
  }
  for (const child of children) if (child !== null && child !== false) node.append(child);
  return node;
}

const field = (label: string, input: HTMLInputElement | HTMLSelectElement) => h("label", {}, h("span", {}, label), input);
const input = (props: Partial<HTMLInputElement>) => h("input", { required: true, maxLength: 128, ...props });
const time = (value: number) => new Date(value * 1000).toLocaleString("zh-HK");
const day = (value: number) => new Date(value * 1000).toLocaleDateString("zh-HK", { month: "long", day: "numeric", weekday: "short" });

function readGrant(): string {
  const match = window.location.hash.match(/^#set-password=([\w-]{43})$/);
  if (!match) return "";
  // Keep the one-time token out of history, bookmarks and screenshots of the address bar.
  history.replaceState(null, "", window.location.pathname + window.location.search);
  return match[1];
}

function renderGate(root: HTMLElement, grant: string, notice = ""): void {
  document.body.classList.add("ngopilot-auth-active");
  const error = h("p", { className: "auth-error", role: "alert", hidden: true });
  const status = h("p", { className: "auth-notice", role: "status", hidden: !notice, textContent: notice });
  const submit = h("button", { className: "auth-submit", type: "submit", textContent: grant ? "設定密碼" : "登入" });
  const form = h("form", { className: "auth-form" },
    !grant && field("電郵", input({ name: "email", type: "email", autocomplete: "username", maxLength: 254 })),
    field(grant ? "新密碼" : "密碼", input({ name: "password", type: "password", autocomplete: grant ? "new-password" : "current-password", minLength: grant ? 15 : 0 })),
    grant && field("確認密碼", input({ name: "confirm", type: "password", autocomplete: "new-password", minLength: 15 })),
    grant && h("p", { className: "auth-hint", textContent: "15–128 個字元，可使用長句。" }),
    error, submit,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    error.hidden = true;
    if (grant && data.get("password") !== data.get("confirm")) {
      error.textContent = "兩次密碼不一致。"; error.hidden = false; return;
    }
    submit.disabled = true;
    try {
      if (grant) {
        await api("/api/auth/set-password", "POST", { token: grant, password: data.get("password") });
        renderGate(root, "", "密碼已設定，請使用電郵和新密碼登入。");
      } else {
        await api("/api/auth/login", "POST", { email: data.get("email"), password: data.get("password") });
        changed();
      }
    } catch (cause) {
      error.textContent = cause instanceof Error ? cause.message : "操作失敗。";
      error.hidden = false;
      submit.disabled = false;
    }
  });
  const help = grant
    ? h("button", { className: "auth-text-button", type: "button", textContent: "返回登入", onclick: () => renderGate(root, "") })
    : h("details", { className: "auth-help" }, h("summary", {}, "忘記密碼或沒有帳號？"),
      h("p", {}, "NGOPilot 不設公開註冊。請聯絡機構管理員核對身份，取得一次性邀請或重設連結。管理員無法登入時，由管理本機的人員執行恢復命令。"));
  root.replaceChildren(h("main", { className: "auth-shell" }, h("section", { className: "auth-panel", "aria-labelledby": "auth-title" },
    h("div", { className: "auth-brand", textContent: "NGOPilot" }),
    h("h1", { id: "auth-title", textContent: grant ? "設定帳號密碼" : "登入 NGOPilot" }),
    h("p", { className: "auth-intro", textContent: grant ? "邀請和重設連結僅可使用一次，1 小時內有效。" : "使用管理員為你開通的機構帳號。每個帳號的對話、附件和文件分開保存。" }),
    status, form, help,
  )));
}

function settingsPage(session: SessionView): void {
  const admin = session.user.role === "ADMIN";
  const message = h("p", { className: "account-message", role: "status", hidden: true });
  const linkBox = h("section", { className: "account-link", hidden: true });
  const devices = h("ul", { className: "account-devices" });
  const users = h("tbody");
  const ownUsage = h("div", { className: "account-usage" });
  const usageHead = h("tr");
  const usageRows = h("tbody");
  const usageNote = h("p");
  const audit = h("tbody");
  let busy = false;
  const close = () => { page.remove(); document.removeEventListener("keydown", escape); };
  const escape = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };

  function show(text: string, error = false) {
    message.textContent = text; message.hidden = !text;
    message.classList.toggle("is-error", error);
    message.setAttribute("role", error ? "alert" : "status");
    if (text) message.scrollIntoView({ block: "nearest" });
  }
  function showLink(link: string) {
    const value = h("input", { readOnly: true, value: link, "aria-label": "一次性連結", onfocus: (event: Event) => (event.target as HTMLInputElement).select() });
    linkBox.replaceChildren(
      h("h2", {}, "一次性設定密碼連結"),
      h("p", {}, "1 小時有效，只顯示這一次。請透過可信渠道私下交付；產生新連結會令舊連結失效。"),
      value,
      h("div", { className: "account-actions" },
        h("button", { type: "button", textContent: "複製", onclick: () => void navigator.clipboard?.writeText(link).then(() => show("已複製連結。")) }),
        h("button", { type: "button", textContent: "隱藏連結", onclick: () => { linkBox.hidden = true; linkBox.replaceChildren(); } })),
    );
    linkBox.hidden = false;
    linkBox.scrollIntoView({ block: "start" });
    value.focus({ preventScroll: true });
  }
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    busy = true; page.classList.add("is-busy"); show("");
    try { await action(); }
    catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) { changed(); return; }
      show(cause instanceof Error ? cause.message : "操作失敗。", true);
    } finally { busy = false; page.classList.remove("is-busy"); }
  }
  async function reload() {
    const [own, people, events, mine, report] = await Promise.all([
      api<{ sessions: Device[] }>("/api/auth/sessions"),
      admin ? api<{ users: Account[] }>("/api/admin/users") : Promise.resolve({ users: [] }),
      admin ? api<{ events: AuditEvent[] }>("/api/admin/audit") : Promise.resolve({ events: [] }),
      api<OwnUsage>("/api/auth/usage"),
      admin ? api<UsageReport>("/api/admin/usage") : Promise.resolve(undefined),
    ]);
    const meter = (label: string, used: number, limit: number | null) => h("div", { className: "account-meter" },
      h("span", {}, label), h("strong", {}, limit ? `${used} / ${limit}` : `${used}`),
      limit ? h("progress", { max: limit, value: Math.min(used, limit) }) : h("small", {}, "管理員不設上限"));
    ownUsage.replaceChildren(
      meter("對話訊息", mine.messages, mine.limits.messages),
      meter("圖片／PDF 處理", mine.images, mine.limits.images),
      h("p", {}, `每週一 00:00（香港時間）重置，下次 ${day(mine.limits.resetsAt)}。在任務卡按「確認」後接續的那條訊息不計入。`),
    );
    if (report) {
      usageNote.textContent = `成員每週上限：對話 ${report.limits.messages ?? "不限"} 條、圖片／PDF ${report.limits.images ?? "不限"} 個；管理員只統計不設上限。格內為「訊息 · 圖片」，括號為核對後接續（不計入）。`;
      usageHead.replaceChildren(h("th", {}, "成員"), ...report.weeks.map((week, index) => h("th", {}, index === 0 ? `本週（${week.slice(5)} 起）` : `${week.slice(5)} 起`)));
      usageRows.replaceChildren(...people.users.map((user) => h("tr", {}, h("td", {}, user.name, h("small", {}, user.role === "ADMIN" ? "管理員" : "成員")),
        ...report.weeks.map((week) => {
          const value = report.usage[user.id]?.[week];
          return h("td", {}, value ? `${value.messages} · ${value.images}${value.continuations ? `（+${value.continuations}）` : ""}` : "—");
        }))));
    }
    devices.replaceChildren(...own.sessions.map((device) => h("li", {}, `${device.current ? "目前登入" : "其他登入"} · 登入於 ${time(device.created_at)}`)));
    users.replaceChildren(...people.users.map(userRow));
    audit.replaceChildren(...events.events.map((event) => h("tr", {},
      h("td", {}, time(event.time)), h("td", {}, event.actor_email ?? "系統／未登入"),
      h("td", {}, actions[event.action] ?? event.action), h("td", {}, event.target_email ?? "—"))));
  }
  function update(user: Account, changes: Partial<Account>) {
    void perform(async () => {
      await api(`/api/admin/users/${user.id}`, "PATCH", { name: user.name, role: user.role, disabled: user.disabled, ...changes });
      await reload(); show("帳號已更新，該帳號已有的登入已撤銷。");
    });
  }
  function userRow(user: Account) {
    const self = user.id === session.user.id;
    const role = h("select", { disabled: self, "aria-label": `${user.email} 角色` },
      h("option", { value: "MEMBER", textContent: "成員" }), h("option", { value: "ADMIN", textContent: "管理員" }));
    role.value = user.role;
    role.addEventListener("change", () => update(user, { role: role.value as Account["role"] }));
    return h("tr", {},
      h("td", {}, user.name, h("small", {}, user.email)),
      h("td", {}, user.disabled ? "已停用" : user.pending ? "待啟用" : "正常"),
      h("td", {}, role),
      h("td", {}, self ? h("small", {}, "（你自己；請用「修改密碼」）") : h("div", { className: "account-actions" },
        h("button", { type: "button", textContent: user.disabled ? "啟用" : "停用", onclick: () => update(user, { disabled: !user.disabled }) }),
        h("button", { type: "button", disabled: user.disabled, textContent: user.pending ? "重新邀請" : "重設密碼",
          onclick: () => void perform(async () => { showLink((await api<{ link: string }>(`/api/admin/users/${user.id}/reset`, "POST")).link); await reload(); }) }))),
    );
  }

  const password = h("form", {},
    field("目前密碼", input({ name: "oldPassword", type: "password", autocomplete: "current-password" })),
    field("新密碼", input({ name: "password", type: "password", autocomplete: "new-password", minLength: 15 })),
    field("確認新密碼", input({ name: "confirm", type: "password", autocomplete: "new-password", minLength: 15 })),
    h("p", {}, "15–128 個字元，可使用長句。修改後所有裝置都需要重新登入。"),
    h("button", { textContent: "修改並重新登入" }));
  password.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(password);
    if (data.get("password") !== data.get("confirm")) { show("兩次密碼不一致。", true); return; }
    void perform(async () => { await api("/api/auth/password", "POST", { oldPassword: data.get("oldPassword"), password: data.get("password") }); changed(); });
  });

  const inviteForm = h("form", { className: "account-invite" },
    field("姓名", input({ name: "name", maxLength: 80, autocomplete: "off" })),
    field("電郵", input({ name: "email", type: "email", maxLength: 254, autocomplete: "off" })),
    field("角色", h("select", { name: "role" }, h("option", { value: "MEMBER", textContent: "成員" }), h("option", { value: "ADMIN", textContent: "管理員" }))),
    h("button", { textContent: "建立邀請" }));
  inviteForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void perform(async () => {
      const result = await api<{ link: string }>("/api/admin/users", "POST", Object.fromEntries(new FormData(inviteForm)));
      showLink(result.link); inviteForm.reset(); await reload();
    });
  });

  const table = (head: string[], body: HTMLElement) => h("div", { className: "account-table" },
    h("table", {}, h("thead", {}, h("tr", {}, ...head.map((label) => h("th", {}, label)))), body));
  const page = h("div", { className: "account-page", role: "dialog", "aria-modal": "true", "aria-labelledby": "account-title" },
    h("div", { className: "account-inner" },
      h("header", {}, h("div", {}, h("h1", { id: "account-title", textContent: "帳號設定" }), h("p", {}, `${session.user.name} · ${session.user.email} · ${admin ? "管理員" : "成員"}`)),
        h("button", { type: "button", textContent: "返回工作台", onclick: close })),
      message, linkBox,
      h("div", { className: "account-columns" },
        h("section", {}, h("h2", {}, "修改密碼"), password),
        h("section", {}, h("h2", {}, "登入狀態"), h("p", {}, "連續 6 小時無操作或登入滿 12 小時後過期。"), devices,
          h("button", { type: "button", textContent: "登出其他裝置",
            onclick: () => void perform(async () => { await api("/api/auth/sessions/revoke-others", "POST"); await reload(); show("其他裝置已登出。"); }) }))),
      h("section", {}, h("h2", {}, "本週用量"), ownUsage),
      admin && h("section", {}, h("h2", {}, "用量統計（最近 4 週）"), usageNote,
        h("div", { className: "account-table" }, h("table", {}, h("thead", {}, usageHead), usageRows))),
      admin && h("section", {}, h("h2", {}, "邀請成員"),
        h("p", {}, "沒有公開註冊。建立後會產生一次性連結，由你私下交給同事設定密碼。"), inviteForm),
      admin && h("section", {}, h("h2", {}, "機構帳號"), table(["成員", "狀態", "角色", "操作"], users)),
      admin && h("section", {}, h("h2", {}, "最近 100 條帳號操作記錄"), table(["時間", "操作者", "操作", "對象"], audit)),
      h("p", { className: "account-note" }, "每個帳號有獨立的對話、附件、核對任務和產生文件。活動 Scheduler（8311 月曆）仍是本機共用工作區，不按帳號分開。"),
    ));
  document.addEventListener("keydown", escape);
  document.body.append(page);
  page.querySelector<HTMLButtonElement>("header button")?.focus();
  void perform(reload);
}

function watch(session: SessionView): void {
  let lastActivity = Date.now();
  const active = () => { lastActivity = Date.now(); };
  const check = () => void api<SessionView>("/api/auth/me").catch((cause) => {
    if (cause instanceof ApiError && cause.status === 401) window.location.reload();
  });
  window.addEventListener("pointerdown", active);
  window.addEventListener("keydown", active);
  window.addEventListener("focus", () => { active(); check(); });
  // Revocation elsewhere takes effect within about 30 seconds on an active page.
  window.setInterval(() => { if (!document.hidden && Date.now() - lastActivity < 60_000) check(); }, 30_000);
  window.setTimeout(() => window.location.reload(), Math.max(0, Math.min(session.expiresAt * 1000 - Date.now(), SESSION_IDLE_MS)));
  if (typeof BroadcastChannel !== "undefined") new BroadcastChannel(CHANNEL).onmessage = () => window.location.reload();
}

/** Resolves only when an account is signed in; otherwise shows the sign-in page. */
export async function requireLocalAccount(root: HTMLElement): Promise<void> {
  // A link pasted into an open tab only changes the hash; restart into the password page.
  window.addEventListener("hashchange", () => {
    if (window.location.hash.startsWith("#set-password=")) window.location.reload();
  });
  const grant = readGrant();
  let session: SessionView | undefined;
  try { session = await api<SessionView>("/api/auth/me"); }
  catch (cause) {
    if (!(cause instanceof ApiError && cause.status === 401)) {
      root.replaceChildren(h("main", { className: "auth-shell" }, h("p", { role: "alert" }, "無法連接 NGOPilot 服務，請確認服務已啟動後重新整理。")));
      return new Promise(() => undefined);
    }
  }
  if (!session || grant) {
    // A password link always wins: an administrator may open a colleague's link on this browser.
    renderGate(root, grant);
    if (typeof BroadcastChannel !== "undefined") new BroadcastChannel(CHANNEL).onmessage = () => window.location.reload();
    return new Promise(() => undefined);
  }
  const current = session;
  window.ngopilotAccount = {
    name: current.user.name, email: current.user.email, role: current.user.role,
    openSettings: () => settingsPage(current),
    logout: async () => { await api("/api/auth/logout", "POST").catch(() => undefined); changed(); },
  };
  watch(current);
}
