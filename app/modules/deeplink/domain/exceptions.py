"""Deeplink domain exceptions."""


class DeepLinkError(Exception):
    """Base for every deeplink failure."""


class DeepLinkNotFoundError(DeepLinkError):
    """Share target does not exist, or the id was malformed. -> 404"""
