import pytest
from pydantic import ValidationError
from app.config import Settings

def test_test_environment_allows_placeholder_secret():
    settings=Settings(database_url='postgresql://test',app_env='test',vapi_secret='change-me')
    assert settings.vapi_secret=='change-me'

def test_production_rejects_placeholder_secret():
    with pytest.raises(ValidationError,match='non-placeholder'):
        Settings(database_url='postgresql://test',app_env='production',vapi_secret=' change-me ')


def test_missing_runtime_config_fails_startup_not_import():
    settings=Settings(database_url='',app_env='development',vapi_secret='test-secret')
    with pytest.raises(ValueError,match='DATABASE_URL'):
        settings.validate_for_startup()
