import { Anchor, Badge, Button, Group, Stack, Text } from "@mantine/core";

import {
  DocType,
  News,
  NewsCategory,
  NewsImportance,
} from "../api/client";

export const CATEGORY_LABEL: Record<number, string> = {
  [NewsCategory.UNSPECIFIED]: "Без категории",
  [NewsCategory.REGULATORY]: "Регуляторика",
  [NewsCategory.REPUTATION]: "Репутация",
  [NewsCategory.COMPETITORS]: "Конкуренты",
  [NewsCategory.TRENDS]: "Тренды",
};

export const IMPORTANCE_LABEL: Record<number, string> = {
  [NewsImportance.UNSPECIFIED]: "Без приоритета",
  [NewsImportance.HIGH]: "Высокая",
  [NewsImportance.MEDIUM]: "Средняя",
  [NewsImportance.LOW]: "Низкая",
};

export const DOC_TYPE_LABEL: Record<number, string> = {
  [DocType.UNSPECIFIED]: "Материал",
  [DocType.NEWS]: "Новость",
  [DocType.NPA]: "НПА",
};

const IMPORTANCE_COLOR: Record<number, string> = {
  [NewsImportance.UNSPECIFIED]: "gray",
  [NewsImportance.HIGH]: "violet",
  [NewsImportance.MEDIUM]: "yellow",
  [NewsImportance.LOW]: "gray",
};

type NewsCardProps = {
  item: News;
  onEdit: (item: News) => void;
  onToggleHidden: (item: News) => void;
  actionsEnabled?: boolean;
  updating?: boolean;
};

function sourceName(url: string, index: number) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace("www.", "");
  } catch {
    return `Источник ${index + 1}`;
  }
}

export default function NewsCard({
  item,
  onEdit,
  onToggleHidden,
  actionsEnabled = true,
  updating,
}: NewsCardProps) {
  const entities = item.entities;
  const hasEntities = !!(
    entities?.who ||
    entities?.what ||
    entities?.when ||
    entities?.consequences
  );

  return (
    <article className={`surface news-card ${item.importance === NewsImportance.HIGH ? "high" : ""}`}>
      <Group justify="space-between" align="flex-start" gap="sm">
        <Group gap={7}>
          <Badge color={IMPORTANCE_COLOR[item.importance]} variant="light" radius="xl">
            {IMPORTANCE_LABEL[item.importance]}
          </Badge>
          <Badge color="dark" variant="outline" radius="xl">
            {CATEGORY_LABEL[item.category]}
          </Badge>
          <Badge color="gray" variant="outline" radius="xl">
            {DOC_TYPE_LABEL[item.docType]}
          </Badge>
          {item.hidden && <Badge color="gray">Скрыто</Badge>}
        </Group>
        <Text size="xs" c="dimmed">
          {item.createdAt ? item.createdAt.toDate().toLocaleDateString("ru-RU") : "Сегодня"}
        </Text>
      </Group>

      <h3 className="news-title">{item.title || "Без заголовка"}</h3>
      <Text className="news-copy">{item.content}</Text>

      {hasEntities && (
        <div className="entity-grid" style={{ marginTop: 18 }}>
          {entities?.who && <div className="entity-cell"><span className="entity-label">Кто</span>{entities.who}</div>}
          {entities?.what && <div className="entity-cell"><span className="entity-label">Что</span>{entities.what}</div>}
          {entities?.when && <div className="entity-cell"><span className="entity-label">Когда</span>{entities.when}</div>}
          {entities?.consequences && <div className="entity-cell"><span className="entity-label">Последствия</span>{entities.consequences}</div>}
        </div>
      )}

      {!!item.tags.length && (
        <Group gap={6} mt="md">
          {item.tags.map((tag) => <Badge key={tag} color="gray" variant="light">#{tag}</Badge>)}
        </Group>
      )}

      <Group justify="space-between" align="flex-end" mt="xl">
        <Stack gap={2}>
          <Text size="xs" c="dimmed">Первоисточники · {item.sources.length || 0}</Text>
          <Group gap="sm">
            {item.sources.slice(0, 3).map((url, index) => (
              <Anchor key={`${url}-${index}`} href={url} target="_blank" rel="noreferrer" size="sm" fw={600}>
                {sourceName(url, index)}
              </Anchor>
            ))}
          </Group>
        </Stack>
        {actionsEnabled && (
          <Group gap="xs">
            <Button variant="subtle" color="dark" size="xs" onClick={() => onEdit(item)}>Изменить</Button>
            <Button variant="light" color={item.hidden ? "violet" : "gray"} size="xs" loading={updating} onClick={() => onToggleHidden(item)}>
              {item.hidden ? "Вернуть" : "Скрыть"}
            </Button>
          </Group>
        )}
      </Group>
    </article>
  );
}
