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

import { api, type RunState } from "../api/client";

const stateColor: Record<RunState, string> = {
  STARTED: "blue",
  DONE: "green",
  FAILED: "red",
};

export default function ProjectPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [runId, setRunId] = useState<string | null>(params.get("run"));

  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.getProject(id) });
  const runs = useQuery({ queryKey: ["runs", id], queryFn: () => api.listRuns(id) });

  // выбрать последний Run, если ничего не выбрано
  useEffect(() => {
    if (!runId && runs.data && runs.data.length > 0) setRunId(runs.data[0].id);
  }, [runId, runs.data]);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = q.state.data?.state;
      return s === "DONE" || s === "FAILED" ? false : 2000;
    },
  });

  const start = useMutation({
    mutationFn: () => api.startRun(id),
    onSuccess: (r) => {
      setRunId(r.id);
      setParams({ run: r.id });
      runs.refetch();
    },
  });

  if (project.isLoading) return <Loader />;
  if (project.isError) return <Alert color="red">{(project.error as Error).message}</Alert>;
  const p = project.data!;

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
        {p.sources.map((s) => (
          <Badge key={s.id} variant="light">
            {s.telegram}
          </Badge>
        ))}
        {p.filters.map((f) => (
          <Badge key={f.id} variant="outline" color="gray">
            {f.prompt}
          </Badge>
        ))}
      </Group>

      {start.isError && <Alert color="red">{(start.error as Error).message}</Alert>}

      {runId && run.data && (
        <Card withBorder padding="md">
          <Group justify="space-between" mb="sm">
            <Badge color={stateColor[run.data.state]}>{run.data.state}</Badge>
            <Text size="sm" c="dimmed">
              {run.data.state === "STARTED"
                ? "обработка…"
                : `собрано ${run.data.stats.collected ?? 0} · релевантно ${
                    run.data.stats.relevant ?? 0
                  } · новостей ${run.data.stats.news ?? 0}`}
            </Text>
          </Group>
          {run.data.stats.error && <Alert color="red">{run.data.stats.error}</Alert>}
          <Stack gap="md">
            {run.data.news.map((n, i) => (
              <div key={i}>
                <Text fw={600}>{n.title}</Text>
                <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                  {n.content}
                </Text>
                <Group gap="xs" mt={4}>
                  {n.sources.map((url, j) => (
                    <Anchor key={j} href={url} target="_blank" size="xs">
                      источник {j + 1}
                    </Anchor>
                  ))}
                </Group>
              </div>
            ))}
            {run.data.state === "DONE" && run.data.news.length === 0 && (
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
