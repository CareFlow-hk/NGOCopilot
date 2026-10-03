const TOKEN_KEY = "ngopilot.auth.token";

export const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } finally {
    localStorage.removeItem(TOKEN_KEY);
    window.location.reload();
  }
}

function saveAccessToken(payload: unknown): void {
  if (!payload || typeof payload !== "object") return;
  const value = payload as Record<string, unknown>;
  const token = value.access_token ?? value.token;
  if (typeof token === "string" && token) {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
  }
  return response;
}

async function jsonRequest(path: string, init: RequestInit = {}): Promise<unknown> {
  const response = await apiFetch(path, init);
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object"
        ? (payload as Record<string, unknown>).detail ??
          (payload as Record<string, unknown>).message
        : null;
    throw new ApiError(typeof detail === "string" ? detail : "請求未完成，請檢查資料後重試", response.status);
  }
  return payload;
}

async function currentUser(): Promise<unknown> {
  return jsonRequest("/api/auth/me");
}

function renderAuthGate(root: HTMLElement): Promise<void> {
  return new Promise((resolve) => {
    let mode: "login" | "register" = "login";

    document.body.classList.add("ngopilot-auth-active");

    root.innerHTML = `
      <main class="auth-shell">
        <section class="auth-panel" aria-labelledby="auth-title">
          <div class="auth-brand">NGOPilot</div>
          <h1 id="auth-title">登入 NGOPilot</h1>
          <p class="auth-intro">工作記錄與產生的檔案會保存在你的帳戶。</p>
          <div class="auth-modes" role="tablist" aria-label="帳戶操作">
            <button type="button" class="is-active" role="tab" aria-selected="true" data-mode="login">登入</button>
            <button type="button" role="tab" aria-selected="false" data-mode="register">建立帳戶</button>
          </div>
          <form class="auth-form">
            <label class="auth-name" hidden>
              <span>姓名</span>
              <input name="name" autocomplete="name" />
            </label>
            <label>
              <span>電郵</span>
              <input name="email" type="email" autocomplete="email" required />
            </label>
            <label>
              <span>密碼</span>
              <input name="password" type="password" autocomplete="current-password" minlength="8" required />
            </label>
            <p class="auth-error" role="alert" hidden></p>
            <button class="auth-submit" type="submit">登入</button>
          </form>
        </section>
      </main>
    `;

    const form = root.querySelector<HTMLFormElement>(".auth-form")!;
    const nameField = root.querySelector<HTMLElement>(".auth-name")!;
    const nameInput = form.elements.namedItem("name") as HTMLInputElement;
    const passwordInput = form.elements.namedItem("password") as HTMLInputElement;
    const submit = root.querySelector<HTMLButtonElement>(".auth-submit")!;
    const error = root.querySelector<HTMLElement>(".auth-error")!;
    const title = root.querySelector<HTMLElement>("#auth-title")!;

    root.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        mode = button.dataset.mode === "register" ? "register" : "login";
        root.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((candidate) => {
          const active = candidate === button;
          candidate.classList.toggle("is-active", active);
          candidate.setAttribute("aria-selected", String(active));
        });
        const registering = mode === "register";
        nameField.hidden = !registering;
        nameInput.required = registering;
        passwordInput.autocomplete = registering ? "new-password" : "current-password";
        title.textContent = registering ? "建立你的帳戶" : "登入 NGOPilot";
        submit.textContent = registering ? "建立帳戶" : "登入";
        error.hidden = true;
      });
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      error.hidden = true;
      submit.disabled = true;
      submit.textContent = mode === "register" ? "正在建立帳戶…" : "正在登入…";

      const values = new FormData(form);
      const body: Record<string, string> = {
        email: String(values.get("email") || "").trim(),
        password: String(values.get("password") || ""),
      };
      if (mode === "register") body.name = String(values.get("name") || "").trim();

      try {
        const payload = await jsonRequest(`/api/auth/${mode}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        saveAccessToken(payload);
        await currentUser();
        document.body.classList.remove("ngopilot-auth-active");
        root.innerHTML = "";
        resolve();
      } catch (cause) {
        error.textContent = cause instanceof Error ? cause.message : "暫時未能繼續，請重試";
        error.hidden = false;
      } finally {
        submit.disabled = false;
        submit.textContent = mode === "register" ? "建立帳戶" : "登入";
      }
    });
  });
}

export async function requireAuthentication(root: HTMLElement): Promise<void> {
  try {
    await currentUser();
  } catch {
    await renderAuthGate(root);
  }
}
