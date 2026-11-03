"""POST /ask: one question in, one validated answer out. Run with: uvicorn src.api.main:app"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from openai import OpenAIError
from pydantic import BaseModel, Field

from src.agent.loop import build_agent
from src.schemas import Answer

log = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@asynccontextmanager
async def lifespan(app):
    app.state.agent = build_agent()
    yield


app = FastAPI(title="Thai Labour-Rights Assistant", lifespan=lifespan)


@app.post("/ask", response_model=Answer)
def ask(request: AskRequest):
    try:
        answer, trace = app.state.agent.run(request.question)
    except OpenAIError as e:
        log.exception("model call failed")
        raise HTTPException(status_code=502, detail="The model service is unavailable") from e
    log.info("tool calls: %s", trace)
    return answer
