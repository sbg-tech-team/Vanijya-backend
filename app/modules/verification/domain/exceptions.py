"""Verification domain exceptions."""


class VerificationError(Exception):
    """Base for every verification business-rule violation. -> 400"""


class KycRequiredError(VerificationError):
    """KYB attempted before KYC completed. -> 400"""


class InvalidKybDocumentError(VerificationError):
    """Wrong KYB document for the profile's role. -> 400"""


class ProfileNotFoundError(Exception):
    """No profile for this user. -> 404"""


class DocumentRejectedError(Exception):
    """The provider answered, and the document is invalid or inactive.

    Not an HTTP error: app_old records it as a `status="error"` row and still
    returns 200. Do not map this to a 4xx.
    """
