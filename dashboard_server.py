import os
import urllib.parse
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import db
import calendar_sync

app = FastAPI(title="Ascentrader AI Growth & Conversion CRM", version="1.0.0")

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "dashboard")
os.makedirs(DASHBOARD_DIR, exist_ok=True)

@app.get("/api/stats/overview")
async def get_overview():
    try:
        data = db.get_dashboard_analytics_summary()
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/ab_test")
async def get_ab_test():
    try:
        data = db.get_dashboard_analytics_summary()
        return JSONResponse(data.get("ab_testing", {}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/funnel")
async def get_funnel():
    try:
        data = db.get_dashboard_analytics_summary()
        return JSONResponse(data.get("funnel", {}))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/leads")
async def get_leads(
    status: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    min_score: Optional[int] = Query(0),
    limit: Optional[int] = Query(50),
    offset: Optional[int] = Query(0)
):
    try:
        data = db.get_leads_crm(
            status_filter=status,
            search=search,
            min_score=min_score,
            limit=limit,
            offset=offset
        )
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/leads/toggle-call")
async def toggle_lead_call(payload: dict):
    profile_url = payload.get("profile_url")
    booked = payload.get("booked")
    if not profile_url:
        raise HTTPException(status_code=400, detail="Missing profile_url")
    try:
        new_val = db.toggle_call_booked(profile_url, booked=booked)
        return JSONResponse({"status": "success", "profile_url": profile_url, "call_booked": new_val})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/calendar/sync")
async def sync_calendar():
    try:
        result = calendar_sync.sync_google_calendar_events()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>Dashboard index.html not found</h2>", status_code=404)

def start_dashboard(host: str = "127.0.0.1", port: int = 8080):
    print(f"\n[OK] Ascentrader Conversion & CRM Dashboard live at http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")

if __name__ == "__main__":
    start_dashboard()
