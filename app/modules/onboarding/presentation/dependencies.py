from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.onboarding.data.adapters.firebase import FirebaseVerifier
from app.modules.onboarding.data.repository import OnboardingRepository
from app.modules.onboarding.domain.interfaces.firebase import IFirebaseVerifier
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository


def get_onboarding_repo(db: Session = Depends(get_db)) -> IOnboardingRepository:
    return OnboardingRepository(db)


def get_firebase_verifier() -> IFirebaseVerifier:
    return FirebaseVerifier()
