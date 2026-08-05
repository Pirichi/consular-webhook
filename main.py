import os
import logging
from fastapi import FastAPI, Request, HTTPException
import requests

# Configuración de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("consular-webhook")

app = FastAPI(title="Consular Notifier Webhook")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "clave_segura_por_defecto")

def send_telegram(message: str) -> bool:
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
        r = requests.post(api_url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")
        return False

@app.get("/")
def health_check():
    return {"status": "online", "service": "Consular Webhook Receiver"}

@app.post("/webhook/{secret_key}")
async def receive_webhook(secret_key: str, request: Request):
    # Validar clave secreta por seguridad para que nadie más spamee tu endpoint
    if secret_key != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Acceso no autorizado")
    
    try:
        body = await request.json()
        logger.info(f"Webhook recibido: {body}")
        
        # Extraer datos o mensaje personalizado enviado en el JSON del webhook
        evento = body.get("evento", "Cambio detectado")
        detalles = body.get("detalles", "Hay movimiento en la agenda consular.")
        
        mensaje = f"🚨 ¡AVISO DE WEBHOOK CONSULAR!\n\n📌 **{evento}**\n📝 {detalles}"
        
        if send_telegram(mensaje):
            return {"status": "success", "message": "Notificación enviada a Telegram correctamente"}
        else:
            raise HTTPException(status_code=500, detail="Error al notificar a Telegram")
            
    except Exception as e:
        logger.error(f"Error procesando el webhook: {e}")
        raise HTTPException(status_code=400, detail="Formato JSON inválido o error interno")
      
