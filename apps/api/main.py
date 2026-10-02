from backend.api.factory import create_app
from backend.domain.config import ApiSettings, load_settings
from backend.infrastructure.database import database_probe, record_heartbeat
from backend.infrastructure.logging import configure_logging

settings = load_settings("api")
assert isinstance(settings, ApiSettings)
configure_logging(settings)
app = create_app(settings, database_probe, record_heartbeat)
