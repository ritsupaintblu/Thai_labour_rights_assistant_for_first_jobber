"""POST /ask: one question in, one validated answer out. Run with: uvicorn src.api.main:app"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from openai import OpenAIError
from pydantic import BaseModel, Field

from src.agent.loop import build_agent
from src.agent.tools.search_law import section_result
from src.schemas import Answer

log = logging.getLogger(__name__)

PAGE = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@asynccontextmanager
async def lifespan(app):
    app.state.agent = build_agent()
    yield


app = FastAPI(title="Thai Labour-Rights Assistant", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return PAGE


@app.get("/section")
def section(law: str, section: str):
    """The in-force text of one section, so a reader can check an answer against the statute itself."""
    result = section_result((law, section))
    if result is None:
        raise HTTPException(status_code=404, detail="No in-force section with that number")
    return {k: result[k] for k in ("law", "section", "amendment_no", "effective_date", "source", "text")}


@app.post("/ask", response_model=Answer)
def ask(request: AskRequest):
    try:
        answer, trace = app.state.agent.run(request.question)
    except OpenAIError as e:
        log.exception("model call failed")
        raise HTTPException(status_code=502, detail="The model service is unavailable") from e
    log.info("tool calls: %s", trace)
    return answer
