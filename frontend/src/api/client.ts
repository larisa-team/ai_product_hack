import { createPromiseClient } from "@connectrpc/connect";
import { createConnectTransport } from "@connectrpc/connect-web";

import { ProjectService, RunService } from "../gen/monitoring/v1/monitoring_connect";

// baseUrl + имя сервиса из proto -> POST /api/monitoring.v1.ProjectService/CreateProject
const transport = createConnectTransport({ baseUrl: "/api" });

export const projectClient = createPromiseClient(ProjectService, transport);
export const runClient = createPromiseClient(RunService, transport);

export * from "../gen/monitoring/v1/monitoring_pb";
