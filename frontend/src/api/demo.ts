import { PartialMessage, Timestamp } from "@bufbuild/protobuf";

import {
  CreateNewsRequest,
  CreateNewsResponse,
  CreateProjectRequest,
  CreateProjectResponse,
  DeleteProjectRequest,
  DeleteProjectResponse,
  DocType,
  GetProjectRequest,
  GetProjectResponse,
  GetRunRequest,
  GetRunResponse,
  ListNewsRequest,
  ListNewsResponse,
  ListProjectsResponse,
  ListRunsRequest,
  ListRunsResponse,
  News,
  NewsCategory,
  NewsEntities,
  NewsImportance,
  Project,
  ProjectFilter,
  Run,
  RunState,
  RunStats,
  Source,
  SourceType,
  StartRunRequest,
  StartRunResponse,
  UpdateNewsRequest,
  UpdateNewsResponse,
  UpdateProjectRequest,
  UpdateProjectResponse,
} from "../gen/monitoring/v1/monitoring_pb";

const DEMO_PROJECT_ID = "demo-gr-monitoring";
const DEMO_RUN_ID = "demo-run-ready";

const now = () => Timestamp.fromDate(new Date());
const daysAgo = (days: number) => Timestamp.fromDate(new Date(Date.now() - days * 86_400_000));
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;

function createSeedNews(): News[] {
  return [
    new News({
      id: 101,
      projectId: DEMO_PROJECT_ID,
      runId: DEMO_RUN_ID,
      title: "Минцифры обновило требования к реестру российского ПО",
      content: "Изменения затрагивают подтверждение происхождения компонентов и сроки подачи документов. Для продуктовой команды это повод проверить текущий пакет сведений и владельцев процесса.",
      sources: ["https://digital.gov.ru/ru/events/"],
      category: NewsCategory.REGULATORY,
      importance: NewsImportance.HIGH,
      docType: DocType.NPA,
      entities: new NewsEntities({
        who: "Минцифры России",
        what: "Обновление требований к реестру ПО",
        when: "Текущий мониторинговый период",
        consequences: "Нужно проверить соответствие продуктовой документации",
      }),
      tags: ["реестр ПО", "регуляторика"],
      createdAt: daysAgo(0),
    }),
    new News({
      id: 102,
      projectId: DEMO_PROJECT_ID,
      runId: DEMO_RUN_ID,
      title: "Крупный облачный провайдер расширил программу импортозамещения",
      content: "Конкурент объявил о новой линейке сервисов и партнёрской программе для корпоративных заказчиков. Сигнал важен для позиционирования и продуктового роадмапа.",
      sources: ["https://t.me/digitalrussia_ru", "https://www.cnews.ru/inc/rss/news.xml"],
      category: NewsCategory.COMPETITORS,
      importance: NewsImportance.MEDIUM,
      docType: DocType.NEWS,
      entities: new NewsEntities({
        who: "Российский облачный провайдер",
        what: "Запуск новой продуктовой программы",
        consequences: "Пересмотреть конкурентные тезисы и пакет для партнёров",
      }),
      tags: ["облака", "конкуренты"],
      createdAt: daysAgo(1),
    }),
    new News({
      id: 103,
      projectId: DEMO_PROJECT_ID,
      runId: DEMO_RUN_ID,
      title: "Бизнес ускоряет внедрение отечественных AI-инструментов",
      content: "В отраслевых источниках растёт число кейсов по локальным AI-решениям. Для компании это подтверждает спрос, но не требует немедленного действия.",
      sources: ["https://www.comnews.ru/rss"],
      category: NewsCategory.TRENDS,
      importance: NewsImportance.LOW,
      docType: DocType.NEWS,
      entities: new NewsEntities({
        who: "Корпоративный рынок",
        what: "Рост интереса к отечественным AI-инструментам",
        consequences: "Использовать в планировании продуктовых коммуникаций",
      }),
      tags: ["AI", "рынок"],
      createdAt: daysAgo(2),
    }),
  ];
}

function createSeedProject(): Project {
  return new Project({
    id: DEMO_PROJECT_ID,
    name: "GR / мониторинг ИТ-рынка",
    topic: "Регулирование российского ПО, репутационные риски и действия конкурентов",
    profile: "Российский разработчик корпоративного ПО. Критичны требования реестра, господдержка, репутационные риски и инициативы облачных конкурентов.",
    collectionDays: 7,
    filters: [
      new ProjectFilter({ prompt: "Исключать вакансии и поздравления" }),
      new ProjectFilter({ prompt: "Исключать материалы без связи с российским ИТ-рынком" }),
    ],
    sources: [
      new Source({ type: SourceType.TELEGRAM, telegram: "digitalrussia_ru", label: "Digital Russia" }),
      new Source({ type: SourceType.RSS, rssUrl: "https://www.cnews.ru/inc/rss/news.xml", label: "CNews" }),
      new Source({ type: SourceType.RSS, rssUrl: "https://www.cbr.ru/rss/RssPress", label: "Банк России" }),
    ],
    createdAt: daysAgo(6),
    updatedAt: now(),
  });
}

function cloneProject(project: Project): Project {
  return Project.fromBinary(project.toBinary());
}

function cloneNews(item: News): News {
  return News.fromBinary(item.toBinary());
}

function cloneRun(run: Run): Run {
  return Run.fromBinary(run.toBinary());
}

export function createDemoClients() {
  const projects = new Map<string, Project>([[DEMO_PROJECT_ID, createSeedProject()]]);
  const news = createSeedNews();
  const runs = new Map<string, Run>([[
    DEMO_RUN_ID,
    new Run({
      id: DEMO_RUN_ID,
      projectId: DEMO_PROJECT_ID,
      createdAt: daysAgo(0),
      state: RunState.DONE,
      stats: new RunStats({ collected: 52, relevant: 31, news: news.length }),
      news: news.map(cloneNews),
    }),
  ]]);
  const runStartedAt = new Map<string, number>();

  const refreshRun = (run: Run) => {
    if (run.state !== RunState.STARTED) return;
    const elapsed = Date.now() - (runStartedAt.get(run.id) ?? Date.now());
    if (elapsed < 1_800) {
      run.stats = new RunStats({ collected: 52, relevant: 0, news: 0, stage: "filtering", stageDone: 18, stageTotal: 52 });
    } else if (elapsed < 3_600) {
      run.stats = new RunStats({ collected: 52, relevant: 31, news: 0, stage: "composing", stageDone: 19, stageTotal: 31 });
    } else {
      run.state = RunState.DONE;
      run.stats = new RunStats({ collected: 52, relevant: 31, news: news.length });
      run.news = news.filter((item) => item.projectId === run.projectId).map(cloneNews);
      runStartedAt.delete(run.id);
    }
  };

  const projectClient = {
    async listProjects(): Promise<ListProjectsResponse> {
      return new ListProjectsResponse({ projects: [...projects.values()].map(cloneProject) });
    },
    async getProject(input: PartialMessage<GetProjectRequest>): Promise<GetProjectResponse> {
      const project = projects.get(input.id ?? "");
      if (!project) throw new Error("Проект не найден");
      return new GetProjectResponse({ project: cloneProject(project) });
    },
    async createProject(input: PartialMessage<CreateProjectRequest>): Promise<CreateProjectResponse> {
      const id = nextId("project");
      const project = new Project({
        id,
        name: input.name ?? "",
        topic: input.topic ?? "",
        profile: input.profile ?? "",
        collectionDays: input.collectionDays || 7,
        filters: (input.filters ?? []).map((item) => new ProjectFilter(item)),
        sources: (input.sources ?? []).map((item) => new Source(item)),
        createdAt: now(),
        updatedAt: now(),
      });
      projects.set(id, project);
      return new CreateProjectResponse({ project: cloneProject(project) });
    },
    async updateProject(input: PartialMessage<UpdateProjectRequest>): Promise<UpdateProjectResponse> {
      const project = projects.get(input.id ?? "");
      if (!project) throw new Error("Проект не найден");
      const paths = new Set(input.updateMask?.paths ?? ["name", "topic", "profile", "collection_days", "filters", "sources"]);
      if (paths.has("name")) project.name = input.name ?? "";
      if (paths.has("topic")) project.topic = input.topic ?? "";
      if (paths.has("profile")) project.profile = input.profile ?? "";
      if (paths.has("collection_days")) project.collectionDays = input.collectionDays || 7;
      if (paths.has("filters")) project.filters = (input.filters ?? []).map((item) => new ProjectFilter(item));
      if (paths.has("sources")) project.sources = (input.sources ?? []).map((item) => new Source(item));
      project.updatedAt = now();
      return new UpdateProjectResponse({ project: cloneProject(project) });
    },
    async deleteProject(input: PartialMessage<DeleteProjectRequest>): Promise<DeleteProjectResponse> {
      const id = input.id ?? "";
      projects.delete(id);
      [...runs.values()].filter((run) => run.projectId === id).forEach((run) => runs.delete(run.id));
      for (let index = news.length - 1; index >= 0; index -= 1) {
        if (news[index].projectId === id) news.splice(index, 1);
      }
      return new DeleteProjectResponse();
    },
  };

  const runClient = {
    async startRun(input: PartialMessage<StartRunRequest>): Promise<StartRunResponse> {
      const projectId = input.projectId ?? "";
      if (!projects.has(projectId)) throw new Error("Проект не найден");
      const id = nextId("run");
      const run = new Run({
        id,
        projectId,
        createdAt: now(),
        state: RunState.STARTED,
        stats: new RunStats({ collected: 52, stage: "filtering", stageDone: 1, stageTotal: 52 }),
      });
      runs.set(id, run);
      runStartedAt.set(id, Date.now());
      return new StartRunResponse({ run: cloneRun(run) });
    },
    async getRun(input: PartialMessage<GetRunRequest>): Promise<GetRunResponse> {
      const run = runs.get(input.id ?? "");
      if (!run) throw new Error("Запуск не найден");
      refreshRun(run);
      return new GetRunResponse({ run: cloneRun(run) });
    },
    async listRuns(input: PartialMessage<ListRunsRequest>): Promise<ListRunsResponse> {
      const items = [...runs.values()]
        .filter((run) => run.projectId === (input.projectId ?? ""))
        .map((run) => {
          refreshRun(run);
          return cloneRun(run);
        })
        .sort((left, right) => (right.createdAt?.toDate().getTime() ?? 0) - (left.createdAt?.toDate().getTime() ?? 0));
      return new ListRunsResponse({ runs: items });
    },
  };

  const newsClient = {
    async listNews(input: PartialMessage<ListNewsRequest>): Promise<ListNewsResponse> {
      const from = input.publishedFrom ? new Timestamp(input.publishedFrom).toDate().getTime() : undefined;
      const to = input.publishedTo ? new Timestamp(input.publishedTo).toDate().getTime() : undefined;
      const query = (input.q ?? "").trim().toLowerCase();
      const items = news.filter((item) => {
        const created = item.createdAt?.toDate().getTime() ?? 0;
        return item.projectId === (input.projectId ?? "")
          && (!(input.categories?.length) || input.categories.includes(item.category))
          && (!(input.importances?.length) || input.importances.includes(item.importance))
          && (!(input.source) || item.sources.includes(input.source))
          && (input.includeHidden || !item.hidden)
          && (!from || created >= from)
          && (!to || created <= to)
          && (!query || `${item.title} ${item.content}`.toLowerCase().includes(query));
      });
      return new ListNewsResponse({ news: items.map(cloneNews), total: items.length });
    },
    async updateNews(input: PartialMessage<UpdateNewsRequest>): Promise<UpdateNewsResponse> {
      const item = news.find((candidate) => candidate.id === input.id);
      if (!item) throw new Error("Событие не найдено");
      const paths = new Set(input.updateMask?.paths ?? []);
      if (paths.has("title")) item.title = input.title ?? "";
      if (paths.has("content")) item.content = input.content ?? "";
      if (paths.has("category")) item.category = input.category ?? NewsCategory.UNSPECIFIED;
      if (paths.has("importance")) item.importance = input.importance ?? NewsImportance.UNSPECIFIED;
      if (paths.has("tags")) item.tags = [...(input.tags ?? [])];
      if (paths.has("hidden")) item.hidden = Boolean(input.hidden);
      return new UpdateNewsResponse({ news: cloneNews(item) });
    },
    async createNews(input: PartialMessage<CreateNewsRequest>): Promise<CreateNewsResponse> {
      const item = new News({
        id: Math.max(100, ...news.map((candidate) => candidate.id)) + 1,
        projectId: input.projectId ?? "",
        title: input.title ?? "",
        content: input.content ?? "",
        category: input.category ?? NewsCategory.UNSPECIFIED,
        importance: input.importance ?? NewsImportance.UNSPECIFIED,
        docType: input.docType ?? DocType.UNSPECIFIED,
        tags: [...(input.tags ?? [])],
        sources: [...(input.sources ?? [])],
        createdAt: now(),
      });
      news.unshift(item);
      return new CreateNewsResponse({ news: cloneNews(item) });
    },
  };

  return { projectClient, runClient, newsClient };
}
