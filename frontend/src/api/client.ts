import { createPromiseClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";

import {
  NewsService,
  ProjectService,
  RunService,
} from "../gen/monitoring/v1/monitoring_connect";
import { createDemoClients } from "./demo";

// baseUrl + имя сервиса из proto -> POST /api/monitoring.v1.ProjectService/CreateProject
const transport = createConnectTransport({ baseUrl: "/api" });

const liveProjectClient = createPromiseClient(ProjectService, transport);
const liveRunClient = createPromiseClient(RunService, transport);
const liveNewsClient = createPromiseClient(NewsService, transport);

export const isDemoMode = import.meta.env.VITE_DEMO_MODE === "true";
const demoClients = createDemoClients();

export const projectClient = (isDemoMode ? demoClients.projectClient : liveProjectClient) as typeof liveProjectClient;
export const runClient = (isDemoMode ? demoClients.runClient : liveRunClient) as typeof liveRunClient;
export const newsClient = (isDemoMode ? demoClients.newsClient : liveNewsClient) as typeof liveNewsClient;

export type HealthStatus = {
  status: "ok" | "degraded";
  db: boolean;
  redis: boolean;
  worker: boolean;
  llm_provider: string;
};

export async function getHealth(): Promise<HealthStatus> {
  if (isDemoMode) {
    return { status: "ok", db: true, redis: true, worker: true, llm_provider: "mock" };
  }
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error("Сервис недоступен");
  return response.json() as Promise<HealthStatus>;
}

export * from "../gen/monitoring/v1/monitoring_pb";
