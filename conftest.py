import pytest


@pytest.fixture(autouse=True)
def _fast_password_hasher(settings):
    """Szybki hasher w testach (domyślny jest celowo wolny)."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
