from fastapi import FastAPI, Response

from backend.api.schemas import HealthLiveness

app = FastAPI(title="Paper simulator foundation", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health/live", response_model=HealthLiveness, operation_id="simulator_health_live")
def live(response: Response) -> HealthLiveness:
    response.headers["Cache-Control"] = "no-store"
    return HealthLiveness(service="simulator")
