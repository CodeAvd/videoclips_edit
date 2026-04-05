from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
