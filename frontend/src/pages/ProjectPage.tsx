import { Timestamp } from "@bufbuild/protobuf";
import {
  Alert,
  Button,
  Checkbox,
  Divider,
  Group,
  Loader,
  Modal,
  Progress,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  DocType,
  getHealth,
  News,
  NewsCategory,
  NewsImportance,
  newsClient,
  projectClient,
  runClient,
  RunState,
  SourceType,
} from "../api/client";
import NewsCard, {
  CATEGORY_LABEL,
  DOC_TYPE_LABEL,
  IMPORTANCE_LABEL,
} from "../components/NewsCard";
import SourceManager from "../components/SourceManager";

const PERIOD_OPTIONS = [
  { value: "1", label: "Сутки" },
  { value: "7", label: "7 дней" },
  { value: "15", label: "15 дней" },
  { value: "30", label: "30 дней" },
];

const STATE_LABEL: Record<number, string> = {
  [RunState.UNSPECIFIED]: "ещё не запускался",
  [RunState.STARTED]: "идёт обработка",
  [RunState.DONE]: "лента обновлена",
  [RunState.FAILED]: "ошибка обработки",
};

const STAGE_LABEL: Record<string, string> = {
  "": "Собираю материалы из источников",
  collecting: "Собираю материалы из источников",
  filtering: "Отсеиваю нерелевантное",
  composing: "Составляю и саммаризирую новости",
};

const CATEGORY_OPTIONS = Object.entries(CATEGORY_LABEL)
  .filter(([value]) => Number(value) !== NewsCategory.UNSPECIFIED)
  .map(([value, label]) => ({ value, label }));

const IMPORTANCE_OPTIONS = Object.entries(IMPORTANCE_LABEL)
  .filter(([value]) => Number(value) !== NewsImportance.UNSPECIFIED)
  .map(([value, label]) => ({ value, label }));

const DOC_TYPE_OPTIONS = Object.entries(DOC_TYPE_LABEL)
  .filter(([value]) => Number(value) !== DocType.UNSPECIFIED)
  .map(([value, label]) => ({ value, label }));

function splitTags(value: string) {
  return value.split(",").map((tag) => tag.trim().replace(/^#/, "")).filter(Boolean);
}

function optionalTimestamp(value: string, endOfDay = false) {
  if (!value) return undefined;
  return Timestamp.fromDate(new Date(`${value}T${endOfDay ? "23:59:59" : "00:00:00"}`));
}

function sourceTitle(source: { type: SourceType; telegram: string; rssUrl: string; label: string }) {
  return source.label || (source.type === SourceType.RSS ? source.rssUrl : source.telegram);
}

export default function ProjectPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [runId, setRunId] = useState<string | null>(params.get("run"));
  const [sourcesOpened, setSourcesOpened] = useState(false);
  const [settingsOpened, setSettingsOpened] = useState(false);
  const [manualOpened, setManualOpened] = useState(false);
  const [selectedNews, setSelectedNews] = useState<News | null>(null);

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [importance, setImportance] = useState<string | null>(null);
  const [docType, setDocType] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [includeHidden, setIncludeHidden] = useState(false);

  const [editName, setEditName] = useState("");
  const [editTopic, setEditTopic] = useState("");
  const [editProfile, setEditProfile] = useState("");
  const [editPeriod, setEditPeriod] = useState("7");
  const [editFilters, setEditFilters] = useState("");

  const [newsTitle, setNewsTitle] = useState("");
  const [newsContent, setNewsContent] = useState("");
  const [newsCategory, setNewsCategory] = useState(String(NewsCategory.TRENDS));
  const [newsImportance, setNewsImportance] = useState(String(NewsImportance.MEDIUM));
  const [newsDocType, setNewsDocType] = useState(String(DocType.NEWS));
  const [newsTags, setNewsTags] = useState("");
  const [newsSources, setNewsSources] = useState("");

  const project = useQuery({
    queryKey: ["project", id],
    queryFn: async () => (await projectClient.getProject({ id })).project!,
    enabled: !!id,
  });

  const health = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 15_000,
    retry: false,
  });

  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: async () => (await runClient.listRuns({ projectId: id, pageSize: 100 })).runs,
    enabled: !!id,
  });

  useEffect(() => {
    if (!runId && runs.data?.length) {
      const latestId = runs.data[0].id;
      setRunId(latestId);
      setParams((current) => {
        current.set("run", latestId);
        return current;
      }, { replace: true });
    }
  }, [runId, runs.data, setParams]);

  useEffect(() => {
    if (!project.data) return;
    setEditName(project.data.name);
    setEditTopic(project.data.topic);
    setEditProfile(project.data.profile);
    setEditPeriod(String(project.data.collectionDays || 7));
    setEditFilters(project.data.filters.map((filter) => filter.prompt).join("\n"));
  }, [project.data]);

  useEffect(() => {
    if (!selectedNews) return;
    setNewsTitle(selectedNews.title);
    setNewsContent(selectedNews.content);
    setNewsCategory(String(selectedNews.category));
    setNewsImportance(String(selectedNews.importance));
    setNewsTags(selectedNews.tags.join(", "));
  }, [selectedNews]);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: async () => (await runClient.getRun({ id: runId! })).run!,
    enabled: !!runId,
    refetchInterval: (current) => current.state.data?.state === RunState.STARTED ? 2_000 : false,
  });

  const newsFeed = useQuery({
    queryKey: ["news", id, category, importance, source, dateFrom, dateTo, query, includeHidden],
    queryFn: async () => newsClient.listNews({
      projectId: id,
      categories: category ? [Number(category) as NewsCategory] : [],
      importances: importance ? [Number(importance) as NewsImportance] : [],
      source: source || "",
      publishedFrom: optionalTimestamp(dateFrom),
      publishedTo: optionalTimestamp(dateTo, true),
      q: query.trim(),
      includeHidden,
      pageSize: 100,
    }),
    enabled: !!id,
    retry: false,
  });

  const start = useMutation({
    mutationFn: async () => {
      const response = await runClient.startRun({ projectId: id });
      if (!response.run) throw new Error("Сервер не вернул запуск");
      return response.run;
    },
    onSuccess: (nextRun) => {
      setRunId(nextRun.id);
      setParams((current) => {
        current.set("run", nextRun.id);
        return current;
      });
      queryClient.invalidateQueries({ queryKey: ["runs", id] });
    },
  });

  const saveSettings = useMutation({
    mutationFn: () => projectClient.updateProject({
      id,
      name: editName.trim(),
      topic: editTopic.trim(),
      profile: editProfile.trim(),
      collectionDays: Number(editPeriod),
      filters: editFilters.split("\n").map((prompt) => prompt.trim()).filter(Boolean).map((prompt) => ({ prompt })),
      updateMask: { paths: ["name", "topic", "profile", "collection_days", "filters"] },
    }),
    onSuccess: () => {
      setSettingsOpened(false);
      queryClient.invalidateQueries({ queryKey: ["project", id] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const saveNews = useMutation({
    mutationFn: () => {
      if (!selectedNews) throw new Error("Новость не выбрана");
      return newsClient.updateNews({
        id: selectedNews.id,
        title: newsTitle.trim(),
        content: newsContent.trim(),
        category: Number(newsCategory) as NewsCategory,
        importance: Number(newsImportance) as NewsImportance,
        tags: splitTags(newsTags),
        updateMask: { paths: ["title", "content", "category", "importance", "tags"] },
      });
    },
    onSuccess: () => {
      setSelectedNews(null);
      queryClient.invalidateQueries({ queryKey: ["news", id] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  const toggleHidden = useMutation({
    mutationFn: (item: News) => newsClient.updateNews({
      id: item.id,
      hidden: !item.hidden,
      updateMask: { paths: ["hidden"] },
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news", id] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  const createNews = useMutation({
    mutationFn: () => newsClient.createNews({
      projectId: id,
      title: newsTitle.trim(),
      content: newsContent.trim(),
      category: Number(newsCategory) as NewsCategory,
      importance: Number(newsImportance) as NewsImportance,
      docType: Number(newsDocType) as DocType,
      tags: splitTags(newsTags),
      sources: newsSources.split("\n").map((url) => url.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      setManualOpened(false);
      setNewsTitle("");
      setNewsContent("");
      setNewsTags("");
      setNewsSources("");
      queryClient.invalidateQueries({ queryKey: ["news", id] });
    },
  });

  const visibleNews = useMemo(() => {
    const primary = newsFeed.data?.news;
    const fallback = run.data?.news || [];
    const items = primary ?? fallback;
    return items.filter((item) => {
      if (!includeHidden && item.hidden) return false;
      if (category && item.category !== Number(category)) return false;
      if (importance && item.importance !== Number(importance)) return false;
      if (docType && item.docType !== Number(docType)) return false;
      if (source && !item.sources.includes(source)) return false;
      if (query.trim() && !`${item.title} ${item.content}`.toLowerCase().includes(query.trim().toLowerCase())) return false;
      const created = item.createdAt?.toDate();
      if (dateFrom && created && created < new Date(`${dateFrom}T00:00:00`)) return false;
      if (dateTo && created && created > new Date(`${dateTo}T23:59:59`)) return false;
      return true;
    });
  }, [newsFeed.data, run.data, includeHidden, category, importance, docType, source, query, dateFrom, dateTo]);

  const highPriority = visibleNews.filter((item) => item.importance === NewsImportance.HIGH && !item.hidden);
  const currentRun = run.data;
  const stats = currentRun?.stats;
  const discarded = Math.max(0, (stats?.collected || 0) - (stats?.relevant || 0));

  const running = currentRun?.state === RunState.STARTED;
  const stage = stats?.stage ?? "";
  const stageDone = stats?.stageDone ?? 0;
  const stageTotal = stats?.stageTotal ?? 0;
  const pct = stageTotal > 0 ? Math.min(100, Math.round((stageDone / stageTotal) * 100)) : null;
  // Показываем только когда запуска нет: во время прогона /api/health периодически
  // моргает worker:false (нагрузка, дрейф часов WSL), а прогресс-бар и так виден.
  const workerDown = health.data ? !health.data.worker && !running : false;
  const sourceOptions = project.data?.sources.map((item) => ({
    value: item.type === SourceType.RSS ? item.rssUrl : item.telegram,
    label: sourceTitle(item),
  })).filter((item) => item.value) || [];

  const clearFilters = () => {
    setQuery("");
    setCategory(null);
    setImportance(null);
    setDocType(null);
    setSource(null);
    setDateFrom("");
    setDateTo("");
    setIncludeHidden(false);
  };

  const openManual = () => {
    setNewsTitle("");
    setNewsContent("");
    setNewsCategory(String(NewsCategory.TRENDS));
    setNewsImportance(String(NewsImportance.MEDIUM));
    setNewsDocType(String(DocType.NEWS));
    setNewsTags("");
    setNewsSources("");
    setManualOpened(true);
  };

  if (project.isLoading) return <div className="surface empty-state"><Loader color="dark" /></div>;
  if (project.isError || !project.data) return <Alert color="red" title="Проект не загружен">{(project.error as Error)?.message || "Проект не найден"}</Alert>;

  return (
    <>
      <section className="dashboard-head">
        <div>
          <p className="eyebrow">Аналитический центр / {STATE_LABEL[currentRun?.state ?? RunState.UNSPECIFIED]}</p>
          <h1 className="dashboard-title">{project.data.name}</h1>
          <p className="dashboard-topic">{project.data.topic}</p>
        </div>
        <Stack align="flex-end" gap="xs">
          <Button size="lg" radius="xl" color="dark" loading={start.isPending || currentRun?.state === RunState.STARTED} onClick={() => start.mutate()}>
            {currentRun?.state === RunState.STARTED ? "Собираем данные…" : "Обновить ленту ↗"}
          </Button>
          <Group gap="md">
            <Button variant="subtle" color="dark" size="xs" onClick={() => setSourcesOpened(true)}>Источники · {project.data.sources.length}</Button>
            <Button variant="subtle" color="dark" size="xs" onClick={() => setSettingsOpened(true)}>Настроить</Button>
            <Button component={Link} to={`/projects/${id}/runs`} variant="subtle" color="dark" size="xs">Запуски</Button>
          </Group>
        </Stack>
      </section>

      {start.isError && <Alert color="red" mb="md">{(start.error as Error).message}</Alert>}

      {workerDown && (
        <Alert color="orange" title="Обработчик недоступен" mb="md">
          Сервис <code>worker</code> не отвечает — новые запуски не обрабатываются.
          Поднимите его: <code>docker compose up -d</code>.
        </Alert>
      )}

      {running && (
        <Alert color="blue" variant="light" mb="md" icon={<Loader size="xs" />}>
          <Group justify="space-between" wrap="nowrap" mb={pct !== null ? 6 : 0}>
            <Text size="sm">{STAGE_LABEL[stage] ?? "Обработка…"}</Text>
            {stageTotal > 0 && <Text size="sm" c="dimmed">{stageDone} / {stageTotal}</Text>}
          </Group>
          {pct !== null && <Progress value={pct} animated size="sm" />}
        </Alert>
      )}

      <section className="metric-grid" aria-label="Метрики последнего запуска">
        <div className="metric-card accent"><div className="metric-label">Собрано</div><div className="metric-value">{stats?.collected ?? 0}</div><Text size="sm">публикаций</Text></div>
        <div className="metric-card"><div className="metric-label">Релевантно</div><div className="metric-value">{stats?.relevant ?? 0}</div><Text size="sm" c="dimmed">прошли фильтр</Text></div>
        <div className="metric-card"><div className="metric-label">Шум</div><div className="metric-value">{discarded}</div><Text size="sm" c="dimmed">отсеяно</Text></div>
        <div className="metric-card"><div className="metric-label">События</div><div className="metric-value">{stats?.news ?? visibleNews.length}</div><Text size="sm" c="dimmed">в ленте</Text></div>
      </section>

      {currentRun?.stats?.error && <Alert color="red" mb="md">{currentRun.stats.error}</Alert>}
      {newsFeed.isError && !!currentRun && (
        <Alert color="violet" variant="light" mb="md" title="Лента в режиме совместимости">
          NewsService ещё не подключён в backend, поэтому показаны события выбранного запуска. Экран не падает и будет автоматически работать с полной лентой после реализации RPC.
        </Alert>
      )}

      {highPriority.length > 0 && (
        <section className="attention-block">
          <p className="eyebrow" style={{ color: "#aaa9a5" }}>Важное / {highPriority.length}</p>
          <h2 className="section-title">Требует внимания</h2>
          <Text mt="md" maw={760} c="#d4d4d0">{highPriority[0].title}</Text>
        </section>
      )}

      <div className="workspace-grid">
        <aside className="surface filter-panel">
          <Group justify="space-between" mb="md">
            <Text fw={800} tt="uppercase" size="sm">Фильтры</Text>
            <Button variant="subtle" color="gray" size="compact-xs" onClick={clearFilters}>Сбросить</Button>
          </Group>
          <Stack gap="sm">
            <TextInput label="Поиск" placeholder="Название или текст" value={query} onChange={(event) => setQuery(event.currentTarget.value)} />
            <Select label="Категория" clearable data={CATEGORY_OPTIONS} value={category} onChange={setCategory} />
            <Select label="Важность" clearable data={IMPORTANCE_OPTIONS} value={importance} onChange={setImportance} />
            <Select label="Тип" clearable data={DOC_TYPE_OPTIONS} value={docType} onChange={setDocType} />
            <Select label="Источник" clearable searchable data={sourceOptions} value={source} onChange={setSource} />
            <div className="form-grid" style={{ gap: 8 }}>
              <TextInput type="date" label="С" value={dateFrom} onChange={(event) => setDateFrom(event.currentTarget.value)} />
              <TextInput type="date" label="По" value={dateTo} onChange={(event) => setDateTo(event.currentTarget.value)} />
            </div>
            <Checkbox label="Показать скрытые" checked={includeHidden} onChange={(event) => setIncludeHidden(event.currentTarget.checked)} />
          </Stack>
          <Divider my="lg" />
          <Stack gap="xs">
            <Button color="dark" onClick={openManual} disabled={!newsFeed.isSuccess}>+ Добавить материал</Button>
            <Button variant="light" color="dark" onClick={() => setSourcesOpened(true)}>Управлять источниками</Button>
          </Stack>
        </aside>

        <section>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Лента / {newsFeed.data?.total || visibleNews.length}</p>
              <h2 className="section-title">События</h2>
            </div>
            {currentRun?.createdAt && <Text size="sm" c="dimmed">Обновлено {currentRun.createdAt.toDate().toLocaleString("ru-RU")}</Text>}
          </div>
          {(newsFeed.isLoading && !run.data) && <div className="surface empty-state"><Loader color="dark" /></div>}
          <div className="feed-stack">
            {visibleNews.map((item) => (
              <NewsCard
                key={item.id || `${item.runId}-${item.title}`}
                item={item}
                actionsEnabled={newsFeed.isSuccess}
                onEdit={setSelectedNews}
                onToggleHidden={(newsItem) => toggleHidden.mutate(newsItem)}
                updating={toggleHidden.isPending && toggleHidden.variables?.id === item.id}
              />
            ))}
          </div>
          {!visibleNews.length && !newsFeed.isLoading && (
            <div className="surface empty-state">
              <div className="empty-state-mark">↘</div>
              <h3 className="project-card-title">Пока нет событий</h3>
              <Text c="dimmed" mb="lg">{runs.data?.length ? "Измените фильтры или обновите ленту." : "Запустите первый сбор по источникам проекта."}</Text>
              <Button color="dark" radius="xl" onClick={() => start.mutate()} loading={start.isPending}>Запустить сбор</Button>
            </div>
          )}
        </section>
      </div>

      <SourceManager projectId={id} sources={project.data.sources} opened={sourcesOpened} onClose={() => setSourcesOpened(false)} />

      <Modal opened={settingsOpened} onClose={() => setSettingsOpened(false)} title={<strong>Настройки проекта</strong>} size="lg" radius="lg" centered>
        <Stack gap="md">
          <TextInput label="Название" value={editName} onChange={(event) => setEditName(event.currentTarget.value)} />
          <Textarea label="Тема мониторинга" autosize minRows={2} value={editTopic} onChange={(event) => setEditTopic(event.currentTarget.value)} />
          <Textarea
            label="Профиль бизнеса"
            description="Важность новостей оценивается по влиянию на этот бизнес. Пусто — по общей значимости."
            autosize
            minRows={2}
            value={editProfile}
            onChange={(event) => setEditProfile(event.currentTarget.value)}
          />
          <Select
            label="Период первичного сбора"
            description="Применяется к новым источникам при первом сборе."
            data={PERIOD_OPTIONS}
            value={editPeriod}
            onChange={(value) => setEditPeriod(value ?? "7")}
            allowDeselect={false}
            w={220}
          />
          <Textarea label="Что исключать" description="Одно указание в строке" autosize minRows={3} value={editFilters} onChange={(event) => setEditFilters(event.currentTarget.value)} />
          {saveSettings.isError && <Alert color="red">{(saveSettings.error as Error).message}</Alert>}
          <Group justify="flex-end"><Button variant="default" onClick={() => setSettingsOpened(false)}>Отмена</Button><Button color="dark" disabled={!editName.trim() || !editTopic.trim()} loading={saveSettings.isPending} onClick={() => saveSettings.mutate()}>Сохранить</Button></Group>
        </Stack>
      </Modal>

      <Modal opened={!!selectedNews} onClose={() => setSelectedNews(null)} title={<strong>Редактор события</strong>} size="lg" radius="lg" centered>
        <Stack gap="md">
          <TextInput label="Заголовок" value={newsTitle} onChange={(event) => setNewsTitle(event.currentTarget.value)} />
          <Textarea label="Саммари" autosize minRows={5} value={newsContent} onChange={(event) => setNewsContent(event.currentTarget.value)} />
          <div className="form-grid"><Select label="Категория" data={CATEGORY_OPTIONS} value={newsCategory} onChange={(value) => setNewsCategory(value || String(NewsCategory.UNSPECIFIED))} /><Select label="Важность" data={IMPORTANCE_OPTIONS} value={newsImportance} onChange={(value) => setNewsImportance(value || String(NewsImportance.UNSPECIFIED))} /></div>
          <TextInput label="Теги" description="Через запятую" value={newsTags} onChange={(event) => setNewsTags(event.currentTarget.value)} />
          {saveNews.isError && <Alert color="red" title="Не удалось сохранить">{(saveNews.error as Error).message}</Alert>}
          <Group justify="flex-end"><Button variant="default" onClick={() => setSelectedNews(null)}>Отмена</Button><Button color="dark" disabled={!newsTitle.trim() || !newsContent.trim()} loading={saveNews.isPending} onClick={() => saveNews.mutate()}>Сохранить</Button></Group>
        </Stack>
      </Modal>

      <Modal opened={manualOpened} onClose={() => setManualOpened(false)} title={<strong>Добавить материал</strong>} size="lg" radius="lg" centered>
        <Stack gap="md">
          <TextInput label="Заголовок" value={newsTitle} onChange={(event) => setNewsTitle(event.currentTarget.value)} />
          <Textarea label="Саммари" autosize minRows={5} value={newsContent} onChange={(event) => setNewsContent(event.currentTarget.value)} />
          <div className="form-grid"><Select label="Категория" data={CATEGORY_OPTIONS} value={newsCategory} onChange={(value) => setNewsCategory(value || String(NewsCategory.UNSPECIFIED))} /><Select label="Важность" data={IMPORTANCE_OPTIONS} value={newsImportance} onChange={(value) => setNewsImportance(value || String(NewsImportance.UNSPECIFIED))} /></div>
          <Select label="Тип материала" data={DOC_TYPE_OPTIONS} value={newsDocType} onChange={(value) => setNewsDocType(value || String(DocType.UNSPECIFIED))} />
          <TextInput label="Теги" description="Через запятую" value={newsTags} onChange={(event) => setNewsTags(event.currentTarget.value)} />
          <Textarea label="Ссылки на источники" description="Одна ссылка в строке" autosize minRows={2} value={newsSources} onChange={(event) => setNewsSources(event.currentTarget.value)} />
          {createNews.isError && <Alert color="red" title="NewsService пока не принял материал">{(createNews.error as Error).message}</Alert>}
          <Group justify="flex-end"><Button variant="default" onClick={() => setManualOpened(false)}>Отмена</Button><Button color="dark" disabled={!newsTitle.trim() || !newsContent.trim()} loading={createNews.isPending} onClick={() => createNews.mutate()}>Добавить</Button></Group>
        </Stack>
      </Modal>
    </>
  );
}
