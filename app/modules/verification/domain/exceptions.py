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
    """The provider answered about THIS document, and it is invalid, inactive
    or does not exist. The user's document is genuinely bad.

    Recorded as `status="rejected"`, and the endpoint still returns 200 — a
    rejection is a result, not a transport failure. Do not map it to a 4xx.
    """


class ProviderUnavailableError(Exception):
    """The provider could not answer about this document at all: expired or
    missing credentials, exhausted quota, a timeout, a 5xx, or a body that was
    not JSON.

    Recorded as `status="provider_unavailable"`, distinct from a rejection,
    because the two are indistinguishable to a user and must not be. Telling
    somebody their PAN failed when in fact our API subscription lapsed is the
    bug this exists to prevent — it happened, for three months.
    """
