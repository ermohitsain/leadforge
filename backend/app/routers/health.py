from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()


@router.get("/health", summary="Health check")
def health_check():
    """Simple liveness probe."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "leadforge-api",
    }


@router.get("/health/ready", summary="Readiness check")
def readiness_check():
    """
    Readiness probe – verifies the database connection is alive.
    Returns 503 if the database is unreachable.
    """
    from fastapi import HTTPException
    from sqlalchemy import text
    from app.database import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    if db_status != "ok":
        raise HTTPException(status_code=503, detail={"database": db_status})

    return {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {"database": db_status},
    }
