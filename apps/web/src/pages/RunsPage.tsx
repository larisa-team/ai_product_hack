import { Anchor, Badge, Loader, Stack, Table, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api, type RunState } from "../api/client";

const stateColor: Record<RunState, string> = {
  STARTED: "blue",
  DONE: "green",
  FAILED: "red",
};

export default function RunsPage() {
  const { id = "" } = useParams();
  const runs = useQuery({ queryKey: ["runs", id], queryFn: () => api.listRuns(id) });
  const project = useQuery({ queryKey: ["project", id], queryFn: () => api.getProject(id) });

  return (
    <Stack gap="md">
      <Title order={4}>
        История запусков{project.data ? ` · ${project.data.name}` : ""}
      </Title>
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
                  {new Date(r.created_at).toLocaleString()}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <Badge color={stateColor[r.state]}>{r.state}</Badge>
              </Table.Td>
              <Table.Td>{r.stats.collected ?? "—"}</Table.Td>
              <Table.Td>{r.stats.relevant ?? "—"}</Table.Td>
              <Table.Td>{r.stats.news ?? "—"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
