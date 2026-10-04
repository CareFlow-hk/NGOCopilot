import "../../../harness bone/ui/desktop/src/styles/main.css";
import "./auth.css";
import "./local-account.css";
import { requireAuthentication } from "./auth";
import { requireLocalAccount } from "./local-account";
import { installBrowserShim } from "./browser-shim";

async function start(): Promise<void> {
  const root = document.getElementById("root");
  if (!root) throw new Error("NGOPilot root element is missing");

  // Local and hosted deployments share Wilson's renderer and the real ACP
  // Agent. Runtime metadata contains display/default settings, never secrets.
  const runtime: Record<string, unknown> = await fetch(`${import.meta.env.VITE_API_URL || ""}/api/runtime`)
    .then((response) => response.ok ? response.json() : {})
    .catch(() => ({}));
  installBrowserShim(runtime);
  // The loopback Agent uses invitation-only cookie sessions; hosted mode keeps bearer tokens.
  await (runtime.NGOPILOT_LOCAL ? requireLocalAccount(root) : requireAuthentication(root));
  await import("@ngopilot/renderer");
}

void start();
