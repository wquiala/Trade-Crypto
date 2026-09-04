from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

app = FastAPI(title="Q-Trade Pro API", version="1.0.0")

# Permitir conexiones desde el Frontend (React/Vite)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción limitar a localhost:5173 o dominio
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot_state = {
    "capital": 0.0,
    "initial_capital": 0.0,
    "kill_switch_active": False,
    "status": "Running",
    "uptime": "0h 0m",
    "active_positions": {},
    "market_scores": {},
    "live_prices": {},
    "trade_history": [],
    "daily_pnl": 0.0
}

@app.get("/api/status")
async def get_status():
    """Retorna el estado general del bot y el capital."""
    return {
        "capital": bot_state["capital"],
        "kill_switch_active": bot_state["kill_switch_active"],
        "status": bot_state["status"],
        "trade_history": bot_state.get("trade_history", []),
        "daily_pnl": bot_state.get("daily_pnl", 0.0)
    }

@app.get("/api/positions")
async def get_positions():
    """Retorna las operaciones actualmente abiertas."""
    return {"positions": bot_state["active_positions"]}

@app.get("/api/market-scores")
async def get_scores():
    """Retorna la última evaluación y los precios en vivo."""
    return {
        "scores": bot_state["market_scores"],
        "prices": bot_state["live_prices"]
    }

@app.post("/api/reset-kill-switch")
async def reset_kill_switch():
    """Permite reactivar el bot reseteando el Kill Switch."""
    bot_state["kill_switch_active"] = False
    bot_state["status"] = "Running"
    bot_state["initial_capital"] = bot_state["capital"]
    bot_state["daily_pnl"] = 0.0
    return {"success": True, "message": "Kill Switch reseteado. Bot reactivado."}

@app.post("/api/trigger-kill-switch")
async def trigger_kill_switch():
    """Permite pausar/detener el bot activando el Kill Switch manualmente."""
    bot_state["kill_switch_active"] = True
    bot_state["status"] = "KillSwitch (Manual)"
    return {"success": True, "message": "Kill Switch activado manualmente. Operativa congelada."}
