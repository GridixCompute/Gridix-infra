import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/errors";

const h = vi.hoisted(() => ({ uploadBlob: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({
  api: { uploadBlob: h.uploadBlob },
  MAX_BLOB_BYTES: 256 * 1024 * 1024,
}));

import { JobInputField } from "./JobInputField";
import type { StagedInput } from "./JobInputField";

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
  render(<JobInputField value={value} onChange={onChange} onUploadingChange={onUploadingChange} />, {
    wrapper,
  });
  return { onChange, onUploadingChange };
}

describe("JobInputField", () => {
  beforeEach(() => h.uploadBlob.mockReset());

  it("uploads the chosen file and reports the ref back to the form", async () => {
    h.uploadBlob.mockResolvedValue({ ref: "blob://sha256:abc", size: 2048 });
    const { onChange } = setup();

    await userEvent.upload(screen.getByLabelText("Job input file"), fileOfSize("data.bin", 2048));

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({ ref: "blob://sha256:abc", name: "data.bin", size: 2048 }),
    );
  });

  it("brackets the upload with onUploadingChange so the form can block submit", async () => {
    h.uploadBlob.mockResolvedValue({ ref: "blob://r", size: 1 });
    const { onUploadingChange } = setup();

    await userEvent.upload(screen.getByLabelText("Job input file"), fileOfSize("d.bin", 1));

    await waitFor(() => expect(onUploadingChange).toHaveBeenCalledWith(false));
    expect(onUploadingChange.mock.calls.map((c) => c[0])).toEqual([true, false]);
  });

  it("rejects an oversize file without uploading it", async () => {
    const { onChange } = setup();

    await userEvent.upload(
      screen.getByLabelText("Job input file"),
      fileOfSize("huge.bin", 256 * 1024 * 1024 + 1),
    );

    expect(h.uploadBlob).not.toHaveBeenCalled();
    expect(await screen.findByText(/the limit is 256\.0 MiB/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ ref: expect.anything() }));
  });

  it("surfaces a failed upload instead of staging a ref", async () => {
    // Thrown inside the async impl, not handed to mockRejectedValue: the latter
    // builds an already-rejected promise before anything awaits it.
    h.uploadBlob.mockImplementation(async () => {
      throw new ApiError({ kind: "server", status: 500, message: "Storage unavailable." });
    });
    const { onChange } = setup();

    await userEvent.upload(screen.getByLabelText("Job input file"), fileOfSize("d.bin", 10));

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
