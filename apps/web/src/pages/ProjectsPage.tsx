import {
  Alert,
  Anchor,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, type ProjectCreate } from "../api/client";

const lines = (s: string) =>
  s
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

export default function ProjectsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });

  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [sources, setSources] = useState("");
  const [filters, setFilters] = useState("");

  const create = useMutation({
    mutationFn: (body: ProjectCreate) => api.createProject(body),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${p.id}`);
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  const submit = () => {
    create.mutate({
      name: name.trim(),
      topic: topic.trim(),
      filters: lines(filters).map((prompt) => ({ prompt })),
      sources: lines(sources).map((telegram) => ({ type: "telegram", telegram })),
    });
  };

  return (
    <Stack gap="xl">
      <Stack gap="xs">
        <Title order={4}>Проекты</Title>
        {isLoading && <Loader size="sm" />}
        {projects?.length === 0 && <Text c="dimmed">Пока нет проектов.</Text>}
        {projects?.map((p) => (
          <Card key={p.id} withBorder padding="sm">
            <Group justify="space-between">
              <div>
                <Anchor component={Link} to={`/projects/${p.id}`} fw={600}>
                  {p.name}
                </Anchor>
                <Text size="sm" c="dimmed">
                  {p.topic} · источников: {p.sources.length}
                </Text>
              </div>
              <Button
                variant="subtle"
                color="red"
                size="xs"
                onClick={() => del.mutate(p.id)}
                loading={del.isPending && del.variables === p.id}
              >
                Удалить
              </Button>
            </Group>
          </Card>
        ))}
      </Stack>

      <Card withBorder padding="md">
        <Title order={5} mb="sm">
          Новый проект
        </Title>
        <Stack gap="sm">
          <TextInput
            label="Название"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
          />
          <TextInput
            label="Тема мониторинга"
            description="По ней LLM решает, что релевантно"
            value={topic}
            onChange={(e) => setTopic(e.currentTarget.value)}
          />
          <Textarea
            label="Telegram-каналы"
            description="По одному в строке: cit_gov, @rfrit, https://t.me/arppsoft"
            autosize
            minRows={3}
            value={sources}
            onChange={(e) => setSources(e.currentTarget.value)}
          />
          <Textarea
            label="Фильтры (необязательно)"
            description="По одному указанию в строке: «не интересны вакансии»"
            autosize
            minRows={2}
            value={filters}
            onChange={(e) => setFilters(e.currentTarget.value)}
          />
          {create.isError && <Alert color="red">{(create.error as Error).message}</Alert>}
          <Button
            onClick={submit}
            loading={create.isPending}
            disabled={!name.trim() || !topic.trim() || lines(sources).length === 0}
          >
            Создать
          </Button>
        </Stack>
      </Card>
    </Stack>
  );
}
