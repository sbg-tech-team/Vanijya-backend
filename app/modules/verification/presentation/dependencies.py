from fastapi import Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.verification.data.adapters.surepass import SurepassVerifier
from app.modules.verification.data.repository import VerificationRepository
from app.modules.verification.domain.interfaces.repository import IVerificationRepository
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier


def get_verification_repo(db: Session = Depends(get_db)) -> IVerificationRepository:
    return VerificationRepository(db)


def get_document_verifier() -> IDocumentVerifier:
    return SurepassVerifier()
