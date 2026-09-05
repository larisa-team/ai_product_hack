import { Alert, Badge, Button, Group, Loader, Table, Text } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { projectClient, runClient, RunState } from "../api/client";

const STATE_COLOR: Record<number, string> = {
  [RunState.UNSPECIFIED]: "gray",
  [RunState.STARTED]: "violet",
  [RunState.DONE]: "green",
  [RunState.FAILED]: "red",
};

const STATE_LABEL: Record<number, string> = {
  [RunState.UNSPECIFIED]: "—",
  [RunState.STARTED]: "идёт",
  [RunState.DONE]: "готово",
  [RunState.FAILED]: "ошибка",
};

export default function RunsPage() {
  const { id = "" } = useParams();
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: async () => (await projectClient.getProject({ id })).project!,
  });
  const runs = useQuery({
    queryKey: ["runs", id],
    queryFn: async () => (await runClient.listRuns({ projectId: id, pageSize: 100 })).runs,
  });

  return (
    <>
      <section className="page-intro" style={{ marginBottom: 30 }}>
        <div>
          <p className="eyebrow">История сборов</p>
          <h1 className="display-title" style={{ fontSize: "clamp(3rem, 7vw, 7rem)" }}>
            Запуски<span className="accent">.</span>
          </h1>
        </div>
        <div>
          <p className="page-lead">
            {project.data ? project.data.name : "Все прогоны мониторинга"}. Здесь видно, сколько материалов собрано, прошло фильтр и превратилось в события.
          </p>
          <Button component={Link} to={`/projects/${id}`} color="dark" radius="xl" mt="lg">← К ленте</Button>
        </div>
      </section>

      {runs.isLoading && <div className="surface empty-state"><Loader color="dark" /></div>}
      {runs.isError && <Alert color="red">{(runs.error as Error).message}</Alert>}
      {runs.data?.length === 0 && (
        <div className="surface empty-state">
          <div className="empty-state-mark">↗</div>
          <h2 className="project-card-title">Запусков пока нет</h2>
          <Text c="dimmed">Вернитесь в проект и запустите первое обновление.</Text>
        </div>
      )}
      {!!runs.data?.length && (
        <div className="surface run-table-wrap">
          <Table verticalSpacing="lg" horizontalSpacing="xl" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Дата</Table.Th>
                <Table.Th>Статус</Table.Th>
                <Table.Th>Собрано</Table.Th>
                <Table.Th>Релевантно</Table.Th>
                <Table.Th>Событий</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runs.data.map((run) => (
                <Table.Tr key={run.id}>
                  <Table.Td><Text fw={700}>{run.createdAt ? run.createdAt.toDate().toLocaleString("ru-RU") : run.id.slice(0, 8)}</Text></Table.Td>
                  <Table.Td><Badge color={STATE_COLOR[run.state]} variant="light" radius="xl">{STATE_LABEL[run.state]}</Badge></Table.Td>
                  <Table.Td>{run.stats?.collected ?? 0}</Table.Td>
                  <Table.Td>{run.stats?.relevant ?? 0}</Table.Td>
                  <Table.Td>{run.stats?.news ?? 0}</Table.Td>
                  <Table.Td>
                    <Group justify="flex-end">
                      <Button component={Link} to={`/projects/${id}?run=${run.id}`} variant="subtle" color="dark" size="xs">Открыть ↗</Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </div>
      )}
    </>
  );
}
