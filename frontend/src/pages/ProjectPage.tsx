import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { projectClient, runClient, RunState } from "../api/client";

const STATE_COLOR: Record<number, string> = {
  [RunState.UNSPECIFIED]: "gray",
  [RunState.STARTED]: "blue",
  [RunState.DONE]: "green",
  [RunState.FAILED]: "red",
};

const STATE_LABEL: Record<number, string> = {
  [RunState.UNSPECIFIED]: "—",
  [RunState.STARTED]: "идёт обработка",
  [RunState.DONE]: "готово",
  [RunState.FAILED]: "ошибка",
};

export default function ProjectPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [runId, setRunId] = useState<string | null>(params.get("run"));

  const project = useQuery({
    queryKey: ["project", id],
    queryFn: async () => (await projectClient.getProject({ id })).project!,
  });

  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: async () => (await runClient.listRuns({ projectId: id })).runs,
  });

  // если ничего не выбрано — показываем последний запуск
  useEffect(() => {
    if (!runId && runs.data && runs.data.length > 0) setRunId(runs.data[0].id);
  }, [runId, runs.data]);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: async () => (await runClient.getRun({ id: runId! })).run!,
    enabled: !!runId,
    refetchInterval: (q) =>
      q.state.data?.state === RunState.STARTED ? 2000 : false,
  });

  const start = useMutation({
    mutationFn: async () => (await runClient.startRun({ projectId: id })).run!,
    onSuccess: (r) => {
      setRunId(r.id);
      setParams({ run: r.id });
      runs.refetch();
    },
  });

  if (project.isLoading) return <Loader />;
  if (project.isError) return <Alert color="red">{(project.error as Error).message}</Alert>;
  const p = project.data!;
  const r = run.data;

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <div>
          <Title order={4}>{p.name}</Title>
          <Text c="dimmed">{p.topic}</Text>
        </div>
        <Group>
          <Anchor component={Link} to={`/projects/${id}/runs`} size="sm">
            История запусков
          </Anchor>
          <Button onClick={() => start.mutate()} loading={start.isPending}>
            Запустить обновление
          </Button>
        </Group>
      </Group>

      <Group gap="xs">
        {p.sources.map((s, i) => (
          <Badge key={i} variant="light">
            {s.telegram}
          </Badge>
        ))}
        {p.filters.map((f, i) => (
          <Badge key={i} variant="outline" color="gray">
            {f.prompt}
          </Badge>
        ))}
      </Group>

      {start.isError && <Alert color="red">{(start.error as Error).message}</Alert>}

      {r && (
        <Card withBorder padding="md">
          <Group justify="space-between" mb="sm">
            <Badge color={STATE_COLOR[r.state]}>{STATE_LABEL[r.state]}</Badge>
            <Text size="sm" c="dimmed">
              {r.state === RunState.STARTED
                ? "собираем и обрабатываем…"
                : `собрано ${r.stats?.collected ?? 0} · релевантно ${
                    r.stats?.relevant ?? 0
                  } · новостей ${r.stats?.news ?? 0}`}
            </Text>
          </Group>

          {r.stats?.error && <Alert color="red">{r.stats.error}</Alert>}

          <Stack gap="md">
            {r.news.map((n, i) => (
              <div key={i}>
                <Text fw={600}>{n.title}</Text>
                <Text size="sm">{n.content}</Text>
                <Group gap="xs" mt={4}>
                  {n.sources.map((url, j) => (
                    <Anchor key={j} href={url} target="_blank" size="xs">
                      источник {j + 1}
                    </Anchor>
                  ))}
                </Group>
              </div>
            ))}
            {r.state === RunState.DONE && r.news.length === 0 && (
              <Text c="dimmed" size="sm">
                Новых новостей нет.
              </Text>
            )}
          </Stack>
        </Card>
      )}
    </Stack>
  );
}
