"""Регистрация реализаций RPC в реестре Connect.

Единственная точка, где proto-сервисы связываются с обработчиками:
модули регистрируют свои методы при импорте.
"""
from __future__ import annotations


def register_all() -> None:
    from app.api import news_api, project_api, run_api  # noqa: F401
