import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("./auth", () => ({
  apiFetch: auth.apiFetch,
  logout: auth.logout,
  ApiError: class ApiError extends Error {
    constructor(
      message: string,
      public readonly status: number,
    ) {
      super(message);
    }
  },
}));

import { installBrowserShim } from "./browser-shim";

describe("browser artifact downloads", () => {
  beforeEach(() => {
    auth.apiFetch.mockReset();
    localStorage.clear();
    document.body.replaceChildren();
    installBrowserShim();
  });

  it("downloads the authorized attachment without opening a popup", async () => {
    const path =
      "/data/tenants/user/workflow/jobs/careflow_paper_forms_to_excel/job-1/outputs/report.xlsx";
    auth.apiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({
          url: "https://storage.example.test/private/report.xlsx?signature=secret",
          filename: "report.xlsx",
        }),
        { status: 200 },
      ),
    );
    const opened = vi.spyOn(window, "open");
    let clickedLink: HTMLAnchorElement | null = null;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      function () {
        clickedLink = this;
      },
    );

    await window.electron.openExternal(path);

    expect(auth.apiFetch).toHaveBeenCalledWith(
      `/api/artifacts/url?path=${encodeURIComponent(path)}`,
    );
    expect(clickedLink).not.toBeNull();
    expect(clickedLink?.href).toBe(
      "https://storage.example.test/private/report.xlsx?signature=secret",
    );
    expect(clickedLink?.download).toBe("report.xlsx");
    expect(opened).not.toHaveBeenCalled();
    expect(document.querySelector("a")).toBeNull();
  });

  it("rejects an incomplete artifact response instead of navigating", async () => {
    auth.apiFetch.mockResolvedValue(
      new Response(
        JSON.stringify({ url: "https://storage.example.test/report.xlsx" }),
        {
          status: 200,
        },
      ),
    );
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click");

    await expect(
      window.electron.openExternal("/data/tenants/user/report.xlsx"),
    ).rejects.toThrow("invalid download URL");
    expect(clicked).not.toHaveBeenCalled();
  });
});
