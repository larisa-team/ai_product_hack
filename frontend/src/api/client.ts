import { createPromiseClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";

import {
  NewsService,
  ProjectService,
  RunService,
} from "../gen/monitoring/v1/monitoring_connect";

// baseUrl + имя сервиса из proto -> POST /api/monitoring.v1.ProjectService/CreateProject
const transport = createConnectTransport({ baseUrl: "/api" });

export const projectClient = createPromiseClient(ProjectService, transport);
export const runClient = createPromiseClient(RunService, transport);
export const newsClient = createPromiseClient(NewsService, transport);

export type HealthStatus = {
  status: "ok" | "degraded";
  db: boolean;
  redis: boolean;
  worker: boolean;
  llm_provider: string;
};

export async function getHealth(): Promise<HealthStatus> {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error("Сервис недоступен");
  return response.json() as Promise<HealthStatus>;
}

export * from "../gen/monitoring/v1/monitoring_pb";
