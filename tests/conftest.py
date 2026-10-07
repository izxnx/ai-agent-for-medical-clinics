import os
os.environ.setdefault('DATABASE_URL','postgresql://test:test@localhost/test')
os.environ.setdefault('VAPI_SECRET','test-secret')
os.environ.setdefault('APP_ENV','test')
import pytest
@pytest.fixture
def anyio_backend():
    return 'asyncio'
