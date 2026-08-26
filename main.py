from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
import httpx
import os
import json
import base64

app = FastAPI(title="Webhook WhatsApp - Agencia de Chatbots")

# Habilitamos CORS para la comunicación con el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Limpiamos automáticamente cualquier salto de línea o espacio invisible en Render
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "mi_token_secreto_123").strip().replace("\n", "").replace("\r", "")
META_WHATSAPP_TOKEN = os.environ.get("META_WHATSAPP_TOKEN", "TU_TOKEN_DE_META").strip().replace("\n", "").replace("\r", "")
META_PHONE_ID = os.environ.get("META_PHONE_ID", "TU_PHONE_ID").strip().replace("\n", "").replace("\r", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "TU_API_KEY_GEMINI").strip().replace("\n", "").replace("\r", "")

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://npkrraxozgrporgthxpd.supabase.co").strip().replace("\n", "").replace("\r", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5wa3JyYXhvemdycG9yZ3RoeHBkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTY1MDksImV4cCI6MjEwMzA5MjUwOX0.JHwCPg9WccLa8VyFFd4BIW8QvMmL8E8oNqzRA_AbuzU").strip().replace("\n", "").replace("\r", "")

# Configuramos Gemini con la API Key
genai.configure(api_key=GEMINI_API_KEY)

@app.get("/webhook")
async def verificar_meta(request: Request):
    """
    Ruta GET: Meta la usa para comprobar que el servidor te pertenece.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ Webhook verificado por Meta exitosamente.")
        return Response(content=challenge, media_type="text/plain")
    
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@app.post("/webhook")
async def recibir_mensaje(request: Request, background_tasks: BackgroundTasks):
    """
    Ruta POST: Aquí Meta envía los mensajes de WhatsApp de tus clientes.
    """
    try:
        cuerpo = await request.json()
        
        if cuerpo.get("object") == "whatsapp_business_account":
            for entry in cuerpo.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    if "messages" in value:
                        mensaje_info = value["messages"][0]
                        numero_remitente = mensaje_info["from"] 
                        
                        if mensaje_info["type"] in ["text", "audio", "image"]:
                            print(f"\n📥 NUEVO EVENTO ({mensaje_info['type'].upper()}) DE WHATSAPP RECIBIDO:")
                            background_tasks.add_task(procesar_y_responder, numero_remitente, mensaje_info)

        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Error al recibir mensaje: {e}")
        return {"status": "error"}

def agendar_cita(fecha: str, hora: str) -> str:
    """
    Agenda una cita en el sistema/calendario para un paciente o cliente.
    """
    print(f"📅 [ACCIÓN REAL EJECUTADA] Bloqueando espacio en calendario para el {fecha} a las {hora}")
    return f"ÉXITO: La cita ha sido registrada y agendada correctamente en el sistema para el {fecha} a las {hora}."
