import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ActivityScheduler from "../../../harness bone/ui/desktop/src/components/schedule/ActivityScheduler";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("ActivityScheduler import review", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    localStorage.setItem("ngopilot.auth.token", "test-token");
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("opens the Review dialog after a PDF extraction response", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/activities")) {
        return Response.json({ activities: [] });
      }
      if (url.endsWith("/api/members")) {
        return Response.json({ members: [] });
      }
      if (url.endsWith("/api/activity-import") && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        return Response.json({
          source_filename: "large-programme.pdf",
          extraction_method: "kimi",
          activities: [
            {
              name: "Tai Chi Class",
              description: null,
              location: "Community Hall",
              activity_code: null,
              sessions: [
                {
                  session_date: "2033-06-10",
                  start_time: "10:00:00",
                  end_time: "11:00:00",
                  raw_date_text: "2033-06-10",
                },
              ],
            },
          ],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(<ActivityScheduler />);
      await Promise.resolve();
    });

    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const pdf = new File(["%PDF test"], "large-programme.pdf", {
      type: "application/pdf",
    });
    Object.defineProperty(input, "files", { configurable: true, value: [pdf] });

    await act(async () => {
      input?.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    const review = container.querySelector<HTMLElement>(
      '[role="dialog"][aria-label="Review imported activities"]',
    );
    expect(review).not.toBeNull();
    expect(review?.textContent).toContain("Review before import");
    expect(review?.textContent).toContain("large-programme.pdf");
    expect(review?.querySelector<HTMLInputElement>('input[value="Tai Chi Class"]')).not.toBeNull();
    expect(review?.querySelector<HTMLInputElement>('input[value="2033-06-10"]')).not.toBeNull();
  });
});
