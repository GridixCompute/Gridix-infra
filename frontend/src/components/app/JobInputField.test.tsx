import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MAX_BLOB_BYTES } from "@/lib/api/browser";
import { JobInputField } from "./JobInputField";
import type { StagedInput } from "./JobInputField";

/**
 * Driven through the real api/ApiClient against a stubbed fetch, so the multipart
 * body and the error mapping are exercised rather than mocked away.
 */
const fetchMock = vi.fn();

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** A File whose reported size we control without allocating the bytes. */
function fileOfSize(name: string, size: number): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function setup(value: StagedInput | null = null) {
  const onChange = vi.fn();
  const onUploadingChange = vi.fn();
  render(
    <JobInputField value={value} onChange={onChange} onUploadingChange={onUploadingChange} />,
    {
      wrapper,
    },
  );
  return { onChange, onUploadingChange };
}

function pick(file: File) {
  return userEvent.upload(screen.getByLabelText("Job input file"), file);
}

describe("JobInputField", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("uploads the chosen file and reports the ref back to the form", async () => {
    fetchMock.mockResolvedValue(json({ ref: "blob://sha256:abc", size: 2048 }, 201));
    const { onChange } = setup();

    await pick(fileOfSize("data.bin", 2048));

    // Controlled component: it reports the ref upward rather than rendering it
    // itself, so the contract is the onChange payload.
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        ref: "blob://sha256:abc",
        name: "data.bin",
        size: 2048,
      }),
    );
  });

  it("posts the file as multipart to /blobs", async () => {
    fetchMock.mockResolvedValue(json({ ref: "blob://r", size: 3 }, 201));
    setup();

    await pick(fileOfSize("data.bin", 3));

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/gw/blobs");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("brackets the upload with onUploadingChange so the form can block submit", async () => {
    fetchMock.mockResolvedValue(json({ ref: "blob://r", size: 1 }, 201));
    const { onUploadingChange } = setup();

    await pick(fileOfSize("d.bin", 1));

    await waitFor(() => expect(onUploadingChange).toHaveBeenCalledWith(false));
    expect(onUploadingChange.mock.calls.map((c) => c[0])).toEqual([true, false]);
  });

  it("rejects an oversize file without uploading it", async () => {
    const { onChange } = setup();

    await pick(fileOfSize("huge.bin", MAX_BLOB_BYTES + 1));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(await screen.findByText(/the limit is 256\.0 MiB/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ ref: expect.anything() }));
  });

  it("surfaces a failed upload instead of staging a ref", async () => {
    fetchMock.mockResolvedValue(json({ detail: "Storage unavailable." }, 500));
    const { onChange } = setup();

    await pick(fileOfSize("d.bin", 10));

    expect(await screen.findByText("Storage unavailable.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ ref: expect.anything() }));
  });

  it("shows the staged file and clears it on remove", async () => {
    const { onChange } = setup({ ref: "blob://sha256:abc", name: "data.bin", size: 2048 });

    expect(screen.getByText("data.bin")).toBeInTheDocument();
    expect(screen.getByText(/2\.0 KiB · blob:\/\/sha256:abc/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
