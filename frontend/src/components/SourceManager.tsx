import {
  Alert,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { projectClient, Source, SourceType } from "../api/client";

type DraftSource = {
  type: SourceType;
  telegram: string;
  rssUrl: string;
  label: string;
  disabled: boolean;
};

const EMPTY_SOURCE: DraftSource = {
  type: SourceType.TELEGRAM,
  telegram: "",
  rssUrl: "",
  label: "",
  disabled: false,
};

type SourceManagerProps = {
  projectId: string;
  sources: Source[];
  opened: boolean;
  onClose: () => void;
};

export default function SourceManager({ projectId, sources, opened, onClose }: SourceManagerProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<DraftSource[]>([]);

  useEffect(() => {
    if (!opened) return;
    setDraft(sources.map((source) => ({
      type: source.type,
      telegram: source.telegram,
      rssUrl: source.rssUrl,
      label: source.label,
      disabled: source.disabled,
    })));
  }, [opened, sources]);

  const save = useMutation({
    mutationFn: () => projectClient.updateProject({
      id: projectId,
      sources: draft,
      updateMask: { paths: ["sources"] },
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onClose();
    },
  });

  const patchSource = (index: number, patch: Partial<DraftSource>) => {
    setDraft((current) => current.map((source, itemIndex) => (
      itemIndex === index ? { ...source, ...patch } : source
    )));
  };

  const invalid = draft.some((source) => (
    source.type === SourceType.RSS ? !source.rssUrl.trim() : !source.telegram.trim()
  ));

  return (
    <Modal opened={opened} onClose={onClose} title={<strong>Источники проекта</strong>} size="xl" radius="lg" centered>
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          RSS подходит для СМИ и сайтов регуляторов. Приостановленные источники сохраняются, но не опрашиваются.
        </Text>
        {draft.map((source, index) => (
          <div className="source-row" key={index}>
            <Select
              label="Тип"
              data={[{ value: String(SourceType.TELEGRAM), label: "Telegram" }, { value: String(SourceType.RSS), label: "RSS / Atom" }]}
              value={String(source.type)}
              onChange={(value) => patchSource(index, { type: Number(value) as SourceType })}
            />
            <TextInput
              label={source.type === SourceType.RSS ? "URL ленты" : "Канал"}
              placeholder={source.type === SourceType.RSS ? "https://example.ru/rss" : "@channel"}
              value={source.type === SourceType.RSS ? source.rssUrl : source.telegram}
              onChange={(event) => patchSource(index, source.type === SourceType.RSS
                ? { rssUrl: event.currentTarget.value }
                : { telegram: event.currentTarget.value })}
            />
            <TextInput label="Ярлык" placeholder="ЦБ РФ / СМИ" value={source.label} onChange={(event) => patchSource(index, { label: event.currentTarget.value })} />
            <Stack gap={4} align="flex-end">
              <Switch checked={!source.disabled} onChange={(event) => patchSource(index, { disabled: !event.currentTarget.checked })} label={source.disabled ? "На паузе" : "Активен"} />
              <Button variant="subtle" color="red" size="compact-xs" onClick={() => setDraft((current) => current.filter((_, itemIndex) => itemIndex !== index))}>Удалить</Button>
            </Stack>
          </div>
        ))}
        {draft.length === 0 && <Text c="dimmed" ta="center" py="md">Источников нет. Их можно добавить сейчас или позже.</Text>}
        <Button variant="light" color="dark" onClick={() => setDraft((current) => [...current, { ...EMPTY_SOURCE }])}>+ Добавить источник</Button>
        {save.isError && <Alert color="red">{(save.error as Error).message}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Отмена</Button>
          <Button color="dark" loading={save.isPending} disabled={invalid} onClick={() => save.mutate()}>Сохранить</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
