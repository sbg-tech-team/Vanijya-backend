"""Read and set the language the user runs the app in (en | hi).

Called during onboarding — after POST /profile/user has created the user
row — and later from settings. The codes are the translation module's.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.onboarding.domain.exceptions import UserNotCreatedError
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository
from app.modules.onboarding.domain.value_objects import APP_LANGUAGES


class AppLanguageUseCase:

    def __init__(self, repository: IOnboardingRepository):
        self.repository = repository

    def get(self, user_id: UUID) -> str:
        lang = self.repository.get_app_language(user_id)
        if lang is None:
            raise UserNotCreatedError("Create the user first (POST /profile/user).")
        return lang

    def set(self, user_id: UUID, app_language: str) -> str:
        if app_language not in APP_LANGUAGES:
            raise ValueError(f"app_language must be one of {list(APP_LANGUAGES)}")
        if not self.repository.set_app_language(user_id, app_language):
            raise UserNotCreatedError("Create the user first (POST /profile/user).")
        return app_language
