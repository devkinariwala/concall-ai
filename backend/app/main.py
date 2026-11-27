import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.core.config import settings
from app.services.monitor import start_background_monitor


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting ConcallAI backend...")
    print(f"AI Model: {settings.gemini_model}")
    monitor_task = asyncio.create_task(start_background_monitor())

    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    print("Shutting down ConcallAI backend...")


app = FastAPI(
    title="ConcallAI",
    description=(
        "AI-powered real-time Indian corporate earnings "
        "concall intelligence platform."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "application": "ConcallAI",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "ai_provider": "Google Gemini",
        "model": settings.gemini_model,
    }