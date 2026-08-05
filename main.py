import os
import asyncio
import logging
import traceback
import httpx
from fastapi import FastAPI, Request, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("consular-monitor")

app = FastAPI(title="Consular Monitor & Webhook")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "clave_segura_por_defecto")

ORIGINAL_HOST = "www.citaconsulares.es"
TARGET_PATH = "/es/hosteds/widgetdefault/2f9880d8d5b8feb958c81d2a08157bcf1/bkt871926"

CLOSURE_PHRASE = "No hay horas disponibles"
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "30"))

monitor_state = {
    "running": True,
    "last_status": "Iniciando...",
    "previous_closed": None
}

async def resolve_doh(domain: str) -> str | None:
    """Resuelve la IP usando el servicio DoH (DNS over HTTPS) de Cloudflare"""
    doh_url = f"https://cloudflare-dns.com/dns-query?name={domain}&type=A"
    headers = {"Accept": "application/dns-json"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(doh_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                answers = data.get("Answer", [])
                for ans in answers:
                    if ans.get("type") == 1:  # Tipo A (IPv4)
                        return ans.get("data")
    except Exception as e:
        logger.warning(f"Fallo en DoH resolution: {e}")
    return None

async def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Faltan las credenciales de Telegram.")
        return False
    
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(api_url, json=payload, timeout=10)
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")
        return False

async def background_monitor():
    logger.info("Monitor con resolución DoH en segundo plano iniciado...")
    
    while monitor_state["running"]:
        try:
            # 1. Resolvemos la IP actual mediante DoH de Cloudflare
            resolved_ip = await resolve_doh(ORIGINAL_HOST)
            if not resolved_ip:
                logger.warning("No se pudo resolver la IP por DoH, reintentando...")
                monitor_state["last_status"] = "Error resolviendo DNS (DoH)"
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            target_url = f"https://{resolved_ip}{TARGET_PATH}"
            headers = {
                "Host": ORIGINAL_HOST,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                response = await client.get(target_url, headers=headers, timeout=20)
                
                if response.status_code != 200:
                    monitor_state["last_status"] = f"Error HTTP {response.status_code}"
                    logger.warning(f"Servidor respondió con estado: {response.status_code}")
                else:
                    page_text = response.text
                    closed_present = CLOSURE_PHRASE.lower() in page_text.lower()
                    
                    monitor_state["last_status"] = "Cerrado / Sin citas" if closed_present else "¡Posible apertura!"
                    
                    if monitor_state["previous_closed"] is None:
                        monitor_state["previous_closed"] = closed_present
                        logger.info(f"Estado inicial registrado: {monitor_state['last_status']}")
                    
                    elif monitor_state["previous_closed"] and not closed_present:
                        logger.info("¡CAMBIO DETECTADO! La frase de cierre ha desaparecido.")
                        msg = "🚨 ¡ATENCIÓN PEDRY! Hay cambios en la agenda consular. ¡Posible apertura de citas!"
                        await send_telegram(msg)
                        monitor_state["previous_closed"] = closed_present
                    else:
                        monitor_state["previous_closed"] = closed_present

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            monitor_state["last_status"] = f"Excepción: {error_msg}"
            logger.error(f"Error en ciclo de monitoreo: {error_msg} \n {traceback.format_exc()}")

        await asyncio.sleep(CHECK_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_monitor())

@app.get("/")
def health_check():
    return {
        "status": "online",
        "monitor": monitor_state
    }

@app.post("/webhook/{secret_key}")
async def receive_webhook(secret_key: str, request: Request):
    if secret_key != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    
    try:
        body = await request.json()
        evento = body.get("evento", "Aviso externo")
        detalles = body.get("detalles", "Notificación recibida vía webhook.")
        
        mensaje = f"🚨 **AVISO EXTERNO**\n\n📌 {evento}\n📝 {detalles}"
        if await send_telegram(mensaje):
            return {"status": "success"}
        else:
            raise HTTPException(status_code=500, detail="Error enviando a Telegram")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
