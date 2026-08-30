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
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens the Review dialog after a PDF extraction response", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/activities")) {
        return Response.json({ activities: [] });
      }
      if (url.endsWith("/api/members")) {
        return Response.json({ members: [] });
      }
      if (url.endsWith("/api/activity-import/jobs") && init?.method === "POST") {
        expect(init.body).toBeInstanceOf(FormData);
        return Response.json({ job_id: "job-1", status: "processing" }, { status: 202 });
      }
      if (url.endsWith("/api/activity-import/jobs/job-1")) {
        return Response.json({
          status: "ready",
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
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(1000);
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

  it("uploads a large PDF in chunks before opening Review", async () => {
    vi.useFakeTimers();
    const totalSize = 8 * 1024 * 1024 + 1;
    const chunkOffsets: number[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/activities")) return Response.json({ activities: [] });
      if (url.endsWith("/api/members")) return Response.json({ members: [] });
      if (url.endsWith("/api/activity-import/uploads")) {
        expect(JSON.parse(String(init?.body))).toEqual({
          filename: "large-programme.pdf",
          size: totalSize,
        });
        return Response.json(
          { upload_id: "upload-1", status: "uploading", received: 0 },
          { status: 201 },
        );
      }
      if (url.includes("/api/activity-import/uploads/upload-1/chunks?offset=")) {
        const offset = Number(new URL(url, "http://localhost").searchParams.get("offset"));
        const chunk = init?.body as Blob;
        chunkOffsets.push(offset);
        return Response.json({
          status: offset + chunk.size === totalSize ? "uploaded" : "uploading",
          received: offset + chunk.size,
        });
      }
      if (url.endsWith("/api/activity-import/uploads/upload-1/complete")) {
        return Response.json({ job_id: "job-large", status: "processing" }, { status: 202 });
      }
      if (url.endsWith("/api/activity-import/jobs/job-large")) {
        return Response.json({
          status: "ready",
          source_filename: "large-programme.pdf",
          activities: [{
            name: "Tai Chi Class",
            description: null,
            location: null,
            activity_code: null,
            sessions: [{
              session_date: "2033-06-10",
              start_time: "10:00:00",
              end_time: "11:00:00",
            }],
          }],
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      root.render(<ActivityScheduler />);
      await Promise.resolve();
    });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const pdf = new File([new Uint8Array(totalSize)], "large-programme.pdf", {
      type: "application/pdf",
    });
    Object.defineProperty(input, "files", { configurable: true, value: [pdf] });

    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(chunkOffsets).toEqual([0, 4 * 1024 * 1024, 8 * 1024 * 1024]);
    expect(
      container.querySelector('[role="dialog"][aria-label="Review imported activities"]'),
    ).not.toBeNull();
  });
});
