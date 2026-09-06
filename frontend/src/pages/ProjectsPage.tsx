import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { projectClient, SourceType } from "../api/client";

type DraftSource = {
  type: SourceType;
  address: string;
  label: string;
};

const EMPTY_SOURCE: DraftSource = {
  type: SourceType.TELEGRAM,
  address: "",
  label: "",
};

const lines = (value: string) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

function sourceLabel(type: SourceType) {
  return type === SourceType.RSS ? "RSS" : "Telegram";
}

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [createOpened, setCreateOpened] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [filters, setFilters] = useState("");
  const [sources, setSources] = useState<DraftSource[]>([{ ...EMPTY_SOURCE }]);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await projectClient.listProjects({ pageSize: 100 })).projects,
  });

  const validSources = useMemo(
    () => sources.filter((source) => source.address.trim()),
    [sources],
  );

  const create = useMutation({
    mutationFn: async () => {
      const response = await projectClient.createProject({
        name: name.trim(),
        topic: topic.trim(),
        filters: lines(filters).map((prompt) => ({ prompt })),
        sources: validSources.map((source) => ({
          type: source.type,
          telegram: source.type === SourceType.TELEGRAM ? source.address.trim() : "",
          rssUrl: source.type === SourceType.RSS ? source.address.trim() : "",
          label: source.label.trim(),
          disabled: false,
        })),
      });
      if (!response.project) throw new Error("Сервер не вернул созданный проект");
      return response.project;
    },
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setCreateOpened(false);
      navigate(`/projects/${project.id}`);
    },
  });

  const removeProject = useMutation({
    mutationFn: (id: string) => projectClient.deleteProject({ id }),
    onSuccess: () => {
      setDeleteId(null);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const patchSource = (index: number, patch: Partial<DraftSource>) => {
    setSources((current) =>
      current.map((source, sourceIndex) =>
        sourceIndex === index ? { ...source, ...patch } : source,
      ),
    );
  };

  return (
    <>
      <section className="hero-stage">
        <div className="hero-orbit" aria-hidden="true" />
        <Group justify="space-between" align="center" className="hero-kicker">
          <p className="eyebrow">AI-powered monitoring / 2026</p>
          <p className="eyebrow">Telegram · RSS · LLM</p>
        </Group>
        <h1 className="home-title">
          <span>Интеллектуальный</span>
          <span>аналитический</span>
          <span className="hero-accent-line"><i aria-hidden="true" />центр</span>
        </h1>
        <div className="hero-bottom">
          <p className="page-lead">
            Одна лента вместо десятков источников. Система собирает материалы,
            убирает дубли, отсекает шум и выделяет то, что требует решения.
          </p>
          <div className="hero-actions">
            <Button size="xl" color="dark" radius="xl" onClick={() => setCreateOpened(true)}>
              Запустить мониторинг&nbsp; ↗
            </Button>
            <div className="hero-mini-stats">
              <div><strong>2</strong><span>типа источников</span></div>
              <div><strong>24/7</strong><span>мониторинг</span></div>
              <div><strong>1</strong><span>лента событий</span></div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div className="section-heading">
          <h2 className="section-title">Проекты</h2>
          <Text c="dimmed" size="sm">
            {projects.data ? `${projects.data.length} активных профилей` : "Загрузка"}
          </Text>
        </div>

        {projects.isLoading && <div className="surface empty-state"><Loader color="dark" /></div>}
        {projects.isError && (
          <Alert color="red" title="Не удалось загрузить проекты">
            Проверьте, что backend запущен и доступен по адресу <code>/api</code>.
          </Alert>
        )}
        {projects.data?.length === 0 && (
          <div className="surface empty-state">
            <div className="empty-state-mark">+</div>
            <h3 className="project-card-title">Начните с темы мониторинга</h3>
            <Text c="dimmed" mb="lg">Добавьте источники и запустите первый сбор.</Text>
            <Button color="dark" radius="xl" onClick={() => setCreateOpened(true)}>Создать проект</Button>
          </div>
        )}

        {!!projects.data?.length && (
          <div className="project-grid">
            {projects.data.map((project, index) => (
              <article className="surface project-card" key={project.id}>
                <div className="project-card-accent" aria-hidden="true" />
                <div className="project-number">{String(index + 1).padStart(2, "0")} / MONITORING</div>
                <div>
                  <Link className="project-card-link" to={`/projects/${project.id}`}>
                    <h3 className="project-card-title">{project.name}</h3>
                  </Link>
                  <Text c="dimmed" lineClamp={2}>{project.topic}</Text>
                  <Group gap={7} mt="md">
                    {project.sources.slice(0, 3).map((source, sourceIndex) => (
                      <Badge key={sourceIndex} variant="light" color="dark" radius="xl">
                        {source.label || sourceLabel(source.type)}
                      </Badge>
                    ))}
                    {project.sources.length > 3 && <Badge variant="outline" color="gray">+{project.sources.length - 3}</Badge>}
                  </Group>
                </div>
                <Group justify="space-between">
                  <Button variant="subtle" color="gray" size="compact-sm" onClick={() => setDeleteId(project.id)}>
                    Удалить
                  </Button>
                  <Link className="project-card-arrow" to={`/projects/${project.id}`} aria-label={`Открыть ${project.name}`}>↗</Link>
                </Group>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="process-section">
        <p className="eyebrow" style={{ color: "#a9a9a5" }}>Как это работает / 3 шага</p>
        <div className="process-heading-row">
          <h2 className="process-title">От потока<br />к решению</h2>
          <Text c="#aaa9a5" maw={430}>
            LLM отвечает за смысл и саммаризацию, а прозрачные фильтры сохраняют контроль у команды.
          </Text>
        </div>
        <div className="process-grid">
          <article><span>01</span><h3>Собираем</h3><p>Telegram-каналы, RSS-ленты СМИ и регуляторов в одном проекте.</p></article>
          <article><span>02</span><h3>Отсекаем</h3><p>Инкрементальный сбор, дедупликация и LLM-фильтр убирают повторы и шум.</p></article>
          <article><span>03</span><h3>Объясняем</h3><p>Каждое событие получает саммари, категорию, важность и ссылки на первоисточники.</p></article>
        </div>
      </section>

      <Modal opened={createOpened} onClose={() => setCreateOpened(false)} title={<strong>Новый проект мониторинга</strong>} size="xl" radius="lg" centered>
        <Stack gap="lg">
          <div className="form-grid">
            <TextInput label="Название" placeholder="Мониторинг рынка ИТ" value={name} onChange={(event) => setName(event.currentTarget.value)} />
            <TextInput label="Тема" placeholder="Цифровые технологии, гранты" value={topic} onChange={(event) => setTopic(event.currentTarget.value)} />
          </div>
          <Textarea label="Что исключать" description="Одно указание в строке" placeholder={"Не интересны вакансии\nИсключать поздравления"} minRows={2} autosize value={filters} onChange={(event) => setFilters(event.currentTarget.value)} />
          <div>
            <Group justify="space-between" mb="xs">
              <Text fw={700}>Источники</Text>
              <Button variant="subtle" color="dark" size="xs" onClick={() => setSources((current) => [...current, { ...EMPTY_SOURCE }])}>+ Добавить</Button>
            </Group>
            {sources.map((source, index) => (
              <div className="source-row" key={index}>
                <Select label="Тип" data={[{ value: String(SourceType.TELEGRAM), label: "Telegram" }, { value: String(SourceType.RSS), label: "RSS / Atom" }]} value={String(source.type)} onChange={(value) => patchSource(index, { type: Number(value) as SourceType })} />
                <TextInput label={source.type === SourceType.RSS ? "URL ленты" : "Канал"} placeholder={source.type === SourceType.RSS ? "https://example.ru/rss" : "@channel"} value={source.address} onChange={(event) => patchSource(index, { address: event.currentTarget.value })} />
                <TextInput label="Ярлык" placeholder="ЦБ РФ / СМИ" value={source.label} onChange={(event) => patchSource(index, { label: event.currentTarget.value })} />
                <Button variant="subtle" color="red" disabled={sources.length === 1} onClick={() => setSources((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Убрать</Button>
              </div>
            ))}
          </div>
          {create.isError && <Alert color="red">{(create.error as Error).message}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCreateOpened(false)}>Отмена</Button>
            <Button color="dark" onClick={() => create.mutate()} loading={create.isPending} disabled={!name.trim() || !topic.trim() || validSources.length === 0}>Создать проект</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={!!deleteId} onClose={() => setDeleteId(null)} title={<strong>Удалить проект?</strong>} centered radius="lg">
        <Text c="dimmed" mb="lg">Проект, запуски и новости будут удалены. Это действие нельзя отменить.</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setDeleteId(null)}>Отмена</Button>
          <Button color="red" loading={removeProject.isPending} onClick={() => deleteId && removeProject.mutate(deleteId)}>Удалить</Button>
        </Group>
      </Modal>
    </>
  );
}
