"""Оценка обогащения карточек: категория / важность / тип документа.

Что делает: гоняет размеченный датасет (`backend/data/eval/enrichment.json`) через
`provider.make_news(...)` — тем же батчингом, что и воркер в `handle_compose`, —
и считает accuracy + confusion matrix по трём измерениям.

Чего НЕ делает: не меняет конвейер. Харнесс дёргает провайдер напрямую, повторяя
только цикл разбивки на батчи. Фильтр релевантности, качество группировки и сущности
здесь не оцениваются.

Запуск на реальном LLM:
    docker compose exec -e LLM_PROVIDER=openai_compat backend python -m app.eval.enrichment
на mock (детерминированно):
    docker compose exec -e LLM_PROVIDER=mock backend python -m app.eval.enrichment
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.llm import schema
from app.llm.provider import LLMProvider, get_provider

DATASET = Path(__file__).resolve().parents[2] / "data" / "eval" / "enrichment.json"

# Измерение -> (ключ метки в датасете, нормализатор в имя enum'а).
DIMENSIONS: dict[str, callable] = {
    "category": schema.category_enum_name,
    "importance": schema.importance_enum_name,
    "doc_type": schema.doc_type_enum_name,
}


@dataclass(slots=True)
class Item:
    id: str
    text: str
    category: str
    importance: str
    doc_type: str


@dataclass(slots=True)
class Prediction:
    item_id: str
    # Имя enum'а либо None — запись не попала ни в одну группу make_news.
    category: str | None
    importance: str | None
    doc_type: str | None


def load_dataset(path: Path = DATASET) -> tuple[str, str, list[Item]]:
    raw = json.loads(path.read_text("utf-8"))
    items = [
        Item(
            id=str(row["id"]),
            text=str(row["text"]),
            category=str(row.get("category", "")),
            importance=str(row.get("importance", "")),
            doc_type=str(row.get("doc_type", "")),
        )
        for row in raw["items"]
    ]
    return str(raw["topic"]), str(raw.get("business", "")), items


async def run(
    provider: LLMProvider,
    topic: str,
    items: list[Item],
    profile: str = "",
    batch_size: int | None = None,
) -> list[Prediction]:
    """Прогон датасета через make_news. Повторяет батч-цикл handle_compose."""
    batch_size = batch_size or settings.NEWSMAKER_BATCH

    # item_id -> предсказанные значения его группы (или None, если группы не нашлось)
    pred: dict[str, dict[str, str | None]] = {
        it.id: {"category": None, "importance": None, "doc_type": None} for it in items
    }

    for offset in range(0, len(items), batch_size):
        batch = items[offset : offset + batch_size]
        payload = [{"i": i, "source": m.id, "text": m.text} for i, m in enumerate(batch)]
        groups = await provider.make_news(topic, payload, profile)
        for g in groups:
            values = {
                "category": schema.category_enum_name(g.get("category")),
                "importance": schema.importance_enum_name(g.get("importance")),
                "doc_type": schema.doc_type_enum_name(g.get("doc_type")),
            }
            for local_i in g.get("message_indices", []):
                if isinstance(local_i, int) and 0 <= local_i < len(batch):
                    pred[batch[local_i].id] = values

    return [
        Prediction(item_id=it.id, **pred[it.id])
        for it in items
    ]


def score(preds: list[Prediction], items: list[Item]) -> dict:
    """Accuracy + coverage + confusion по каждому измерению."""
    label_by_id = {it.id: it for it in items}
    total = len(items)
    result: dict = {"total": total, "dimensions": {}}

    for dim, normalize in DIMENSIONS.items():
        correct = attributed = correct_attr = 0
        confusion: dict[str, dict[str, int]] = {}
        for p in preds:
            gold = normalize(getattr(label_by_id[p.item_id], dim))
            got = getattr(p, dim)  # уже имя enum'а либо None
            got_key = got or "—MISSING—"
            confusion.setdefault(gold, {})
            confusion[gold][got_key] = confusion[gold].get(got_key, 0) + 1
            if got is not None:
                attributed += 1
                if got == gold:
                    correct_attr += 1
            if got == gold:
                correct += 1
        result["dimensions"][dim] = {
            # accuracy — MISSING (запись не попала ни в одну группу) считается промахом:
            # так метрика отражает реальный продукт (нет карточки — нет разметки).
            "accuracy": correct / total if total else 0.0,
            # accuracy_attr — только по записям, попавшим в группу: чистое качество
            # классификации, без наказания за агрессивную группировку модели.
            "accuracy_attr": correct_attr / attributed if attributed else 0.0,
            "coverage": attributed / total if total else 0.0,
            "correct": correct,
            "correct_attr": correct_attr,
            "attributed": attributed,
            "confusion": confusion,
        }

    result["coverage"] = (
        sum(1 for p in preds if p.category is not None) / total if total else 0.0
    )
    return result


def _short(enum_name: str) -> str:
    return enum_name.split("_")[-1][:8] if enum_name != "—MISSING—" else "MISSING"


def format_report(sc: dict, meta: dict) -> str:
    lines: list[str] = []
    lines.append(
        f"=== Enrichment eval: {sc['total']} записей, provider={meta.get('provider')}"
        f", profile={'да' if meta.get('profile') else 'нет'} ==="
    )
    lines.append("")
    for dim, d in sc["dimensions"].items():
        lines.append(
            f"{dim:<11} accuracy {d['accuracy']:.2f} ({d['correct']}/{sc['total']})   "
            f"acc_attr {d['accuracy_attr']:.2f} ({d['correct_attr']}/{d['attributed']})   "
            f"coverage {d['coverage']:.2f}"
        )
    lines.append("")
    for dim, d in sc["dimensions"].items():
        conf = d["confusion"]
        preds_seen = sorted({k for row in conf.values() for k in row})
        lines.append(f"{dim} confusion (строки — метка, столбцы — предсказание):")
        header = " " * 12 + "".join(f"{_short(p):>9}" for p in preds_seen)
        lines.append(header)
        for gold in sorted(conf):
            row = conf[gold]
            cells = "".join(f"{row.get(p, 0):>9}" for p in preds_seen)
            lines.append(f"{_short(gold):>11} {cells}")
        lines.append("")
    return "\n".join(lines)


async def _amain(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DATASET
    topic, profile, items = load_dataset(path)
    provider = get_provider()
    preds = await run(provider, topic, items, profile)
    sc = score(preds, items)
    meta = {"provider": settings.LLM_PROVIDER, "profile": bool(profile)}
    print(format_report(sc, meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_amain(sys.argv[1:])))
