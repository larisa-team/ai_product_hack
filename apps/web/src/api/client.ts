export type RunState = "STARTED" | "DONE" | "FAILED";

export interface Filter {
  id: string;
  prompt: string;
}
export interface Source {
  id: string;
  type: string;
  telegram: string;
}
export interface Project {
  id: string;
  name: string;
  topic: string;
  filters: Filter[];
  sources: Source[];
  created_at: string;
  updated_at: string;
}
export interface News {
  title: string;
  content: string;
  sources: string[];
}
export interface RunStats {
  collected?: number;
  relevant?: number;
  news?: number;
  error?: string;
}
export interface RunSummary {
  id: string;
  project_id: string;
  state: RunState;
  created_at: string;
  finished_at: string | null;
  stats: RunStats;
}
export interface Run extends RunSummary {
  news: News[];
}

export interface ProjectCreate {
  name: string;
  topic: string;
  filters: { prompt: string }[];
  sources: { type: string; telegram: string }[];
}

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => req<Project[]>("/projects"),
  getProject: (id: string) => req<Project>(`/projects/${id}`),
  createProject: (body: ProjectCreate) =>
    req<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  deleteProject: (id: string) => req<void>(`/projects/${id}`, { method: "DELETE" }),
  startRun: (id: string) => req<RunSummary>(`/projects/${id}/runs`, { method: "POST" }),
  getRun: (id: string) => req<Run>(`/runs/${id}`),
  listRuns: (id: string) => req<RunSummary[]>(`/projects/${id}/runs`),
};
