from backend.api.factory import create_bridge_app
from backend.domain.config import BridgeSettings, load_settings
from backend.infrastructure.database import database_probe, record_heartbeat
from backend.infrastructure.logging import configure_logging

settings = load_settings("risk")
assert isinstance(settings, BridgeSettings)
configure_logging(settings)
app = create_bridge_app(settings, database_probe, record_heartbeat)
