from fastapi import APIRouter, HTTPException, Request

from app.api.deps import Auth, DbSession, correlation_id
from app.schemas.search import AskRequest, AskResponse, SearchRequest, SearchResponse
from app.services.answering import generate_grounded_answer
from app.services.audit import add_audit_log
from app.services.openrouter import ModelProviderError
from app.services.retrieval import semantic_search

router = APIRouter(tags=["knowledge"])


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, request: Request, auth: Auth, db: DbSession) -> SearchResponse:
    try:
        response = await semantic_search(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            payload=payload,
            correlation_id=correlation_id(request),
        )
    except ModelProviderError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="SEMANTIC_SEARCH",
        resource_type="search_query",
        resource_id=response.query_id,
        correlation_id=correlation_id(request),
        details={"result_count": len(response.results)},
    )
    await db.commit()
    return response


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request, auth: Auth, db: DbSession) -> AskResponse:
    try:
        search_response = await semantic_search(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            payload=payload,
            correlation_id=correlation_id(request),
        )
        response = await generate_grounded_answer(
            db,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            question=payload.query,
            search=search_response,
            correlation_id=correlation_id(request),
        )
    except ModelProviderError as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="GROUNDED_ANSWER",
        resource_type="answer_generation",
        resource_id=response.answer_id,
        correlation_id=correlation_id(request),
        details={"evidence_sufficient": response.evidence_sufficient},
    )
    await db.commit()
    return response

