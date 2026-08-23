from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
import httpx # Para hacer peticiones HTTP a WhatsApp
import os
import json

app = FastAPI(title="Webhook WhatsApp - Agencia de Chatbots")

# Habilitamos CORS por si conectas tu panel de React en el futuro
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# CONFIGURACIÓN (Variables de Entorno)
# ==========================================
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "mi_token_secreto_123")
META_WHATSAPP_TOKEN = os.environ.get("META_WHATSAPP_TOKEN", "TU_TOKEN_DE_META")
META_PHONE_ID = os.environ.get("META_PHONE_ID", "TU_PHONE_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "TU_API_KEY_GEMINI")

# Configuramos Gemini con tu llave
genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# RUTAS DEL WEBHOOK
# ==========================================

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
        print("\n📥 NUEVO EVENTO DE WHATSAPP REBIDO:")
        
        # Verificamos si hay mensajes nuevos
        if cuerpo.get("object") == "whatsapp_business_account":
            for entry in cuerpo.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    if "messages" in value:
                        mensaje_info = value["messages"][0]
                        numero_remitente = mensaje_info["from"] 
                        
                        if mensaje_info["type"] == "text":
                            texto_recibido = mensaje_info["text"]["body"]
                            print(f"💬 Mensaje de {numero_remitente}: {texto_recibido}")
                            
                            # Procesamos con Gemini en segundo plano para no hacer esperar a Meta
                            background_tasks.add_task(procesar_y_responder, numero_remitente, texto_recibido)

        # SIEMPRE debemos responder 200 OK a Meta
        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error"}

# ==========================================
# LÓGICA DEL BOT Y CONEXIÓN CON GEMINI
# ==========================================

async def procesar_y_responder(numero_telefono: str, mensaje_usuario: str):
    """
    Habla con Gemini y le manda la respuesta al cliente.
    """
    print(f"🧠 Procesando respuesta para {numero_telefono} con Gemini...")
    
    try:
        # Contexto del bot (Instrucciones que le das como agencia)
        contexto = "Eres el asistente de la Clínica Aurora. Eres amable y conciso. No das precios exactos, pides que agenden cita."
        
        modelo = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"Instrucciones: {contexto}\n\nPaciente: {mensaje_usuario}\nAsistente:"
        
        respuesta_gemini = modelo.generate_content(prompt)
        texto_respuesta = respuesta_gemini.text
        
        print(f"🤖 Bot responde: {texto_respuesta}")
        
        # Enviamos el mensaje de vuelta a WhatsApp
        await enviar_mensaje_whatsapp(numero_telefono, texto_respuesta)
        
    except Exception as e:
        print(f"❌ Error al procesar con Gemini: {e}")

async def enviar_mensaje_whatsapp(numero_destino: str, texto: str):
    """
    Usa la API de Meta para mandar el mensaje de vuelta al celular del cliente.
    """
    url = f"https://graph.facebook.com/v19.0/{META_PHONE_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {META_WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": numero_destino,
        "type": "text",
        "text": { "body": texto }
    }
    
    async with httpx.AsyncClient() as client:
        respuesta = await client.post(url, headers=headers, json=payload)
        
        if respuesta.status_code == 200:
            print(f"✅ Mensaje enviado a {numero_destino}")
        else:
            print(f"❌ Error de Meta: {respuesta.text}")