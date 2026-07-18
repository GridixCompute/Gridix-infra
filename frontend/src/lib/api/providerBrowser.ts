"use client";

import { ApiClient } from "./client";
import type {
  Provider,
  ProviderCapabilities,
  ProviderJobAttempt,
  ReputationEvent,
  BenchmarkResponse,
  BandwidthResponse,
  DisputeResponse,
} from "./types";

/**
 * Provider API surface (Session 11). Same discipline as the developer surface:
 * every call goes through the same-origin authenticated proxy (/api/gw), so the
 * agent key never reaches browser JS, and all return types come from the
 * generated OpenAPI schema.
 */
const gw = new ApiClient({ baseUrl: "/api/gw" });

export type TrustInfo = {
  attested: boolean;
  benchmarked: boolean;
  trust_source: "attested" | "benchmark" | "self_report";
};

export const providerApi = {
  me(signal?: AbortSignal): Promise<Provider> {
    return gw.get<Provider>("/providers/me", { signal, retries: 2 });
  },
  updateCapabilities(body: ProviderCapabilities): Promise<Provider> {
    return gw.patch<Provider>("/providers/me", body);
  },
  benchmark(signal?: AbortSignal): Promise<BenchmarkResponse | null> {
    return gw.get<BenchmarkResponse | null>("/providers/me/benchmark", { signal, retries: 2 });
  },
  trust(signal?: AbortSignal): Promise<TrustInfo> {
    return gw.get<TrustInfo>("/providers/me/trust", { signal, retries: 2 });
  },
  bandwidth(signal?: AbortSignal): Promise<BandwidthResponse> {
    return gw.get<BandwidthResponse>("/providers/me/bandwidth", { signal, retries: 2 });
  },
  jobs(limit = 50, signal?: AbortSignal): Promise<ProviderJobAttempt[]> {
    return gw.get<ProviderJobAttempt[]>(`/providers/me/jobs?limit=${limit}`, {
      signal,
      retries: 2,
    });
  },
  reputation(limit = 50, signal?: AbortSignal): Promise<ReputationEvent[]> {
    return gw.get<ReputationEvent[]>(`/providers/me/reputation?limit=${limit}`, {
      signal,
      retries: 2,
    });
  },
  disputes(signal?: AbortSignal): Promise<DisputeResponse[]> {
    return gw.get<DisputeResponse[]>("/disputes/me", { signal, retries: 2 });
  },
  contestDispute(id: string): Promise<DisputeResponse> {
    return gw.post<DisputeResponse>(`/disputes/${id}/contest`);
  },
};
