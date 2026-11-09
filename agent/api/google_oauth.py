"""Safe Google OAuth endpoints for the local Electron application."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from agent.services.google_oauth import (
    GoogleAuthError, complete_authorization, connection_status,
    create_authorization_url, disconnect,
)

router = APIRouter(prefix="/oauth/google", tags=["google-oauth"])


@router.get("/start")
async def start_google_oauth():
    try:
        return {"authorizationUrl": await create_authorization_url()}
    except GoogleAuthError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/callback", response_class=HTMLResponse)
async def google_oauth_callback(code: str = Query(...), state: str = Query(...)):
    try:
        await complete_authorization(code, state)
    except GoogleAuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return HTMLResponse("<h2>Google connected</h2><p>You may close this tab and return to HBG Video Studio.</p>")


@router.get("/status")
async def google_oauth_status():
    return await connection_status()


@router.delete("/connection")
async def disconnect_google():
    await disconnect()
    return {"status": "not_connected"}
