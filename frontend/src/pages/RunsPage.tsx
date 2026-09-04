import { Anchor, Badge, Loader, Stack, Table, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { projectClient, runClient, RunState } from "../api/client";

const STATE_COLOR: Record<number, string> = {
  [RunState.UNSPECIFIED]: "gray",
  [RunState.STARTED]: "blue",
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
    queryFn: async () => (await runClient.listRuns({ projectId: id })).runs,
  });

  return (
    <Stack gap="md">
      <Title order={4}>История запусков{project.data ? ` · ${project.data.name}` : ""}</Title>
      <Anchor component={Link} to={`/projects/${id}`} size="sm">
        ← к проекту
      </Anchor>
      {runs.isLoading && <Loader size="sm" />}
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Запуск</Table.Th>
            <Table.Th>Статус</Table.Th>
            <Table.Th>Собрано</Table.Th>
            <Table.Th>Релевантно</Table.Th>
            <Table.Th>Новостей</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.data?.map((r) => (
            <Table.Tr key={r.id}>
              <Table.Td>
                <Anchor component={Link} to={`/projects/${id}?run=${r.id}`}>
                  {r.createdAt ? r.createdAt.toDate().toLocaleString() : r.id.slice(0, 8)}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <Badge color={STATE_COLOR[r.state]}>{STATE_LABEL[r.state]}</Badge>
              </Table.Td>
              <Table.Td>{r.stats?.collected ?? 0}</Table.Td>
              <Table.Td>{r.stats?.relevant ?? 0}</Table.Td>
              <Table.Td>{r.stats?.news ?? 0}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
