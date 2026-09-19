"""
Application entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000

Mounts:
  /api/*      - the agentic system's own API (chat, tools, rag, etc.)
  /paypal/*   - the mock PayPal API (browsable directly at /docs too)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.mock_paypal import router as paypal_router

app = FastAPI(
    title="Scalable Agentic System for Intelligent Tool Selection and Execution",
    description="Hierarchical tool retrieval + ranking + planning + execution over a PayPal-like API surface.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(paypal_router)


@app.get("/")
def root():
    return {
        "service": "Scalable Agentic System",
        "docs": "/docs",
        "api_base": "/api",
        "mock_paypal_base": "/paypal",
    }
