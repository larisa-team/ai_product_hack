import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes } from "react-router-dom";

import { getHealth, isDemoMode } from "./api/client";
import ProjectPage from "./pages/ProjectPage";
import ProjectsPage from "./pages/ProjectsPage";
import RunsPage from "./pages/RunsPage";

export default function App() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  });

  const healthLabel = health.isError
    ? "API недоступен"
    : health.data?.status === "ok"
      ? "Система в норме"
      : "Проверка системы";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="brand" to="/" aria-label="Сигнал — главная">
            <span className="brand-mark" aria-hidden="true" />
            <span className="brand-name">Сигнал<span>/</span>центр</span>
          </Link>
          <nav className="topbar-nav" aria-label="Основная навигация">
            <NavLink to="/" end>Проекты</NavLink>
            {isDemoMode
              ? <span className="demo-mode-badge" title="Данные обрабатываются встроенным mock-провайдером">DEMO · MOCK</span>
              : <a href="/api/health" target="_blank" rel="noreferrer">Статус API</a>}
          </nav>
          <div className="system-pill" title="Статус backend, базы и воркера">
            <span
              className={`status-dot ${
                health.data?.status === "ok" ? "ok" : health.isError ? "" : "warn"
              }`}
            />
            {healthLabel}
          </div>
        </div>
      </header>
      <main className="page-shell">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/projects/:id/news" element={<ProjectPage />} />
          <Route path="/projects/:id/runs" element={<RunsPage />} />
        </Routes>
      </main>
    </div>
  );
}
