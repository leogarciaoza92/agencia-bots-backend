from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
import httpx # Para peticiones HTTP a WhatsApp y Supabase
import os
import json

app = FastAPI(title="Webhook WhatsApp - Agencia de Chatbots")

# Habilitamos CORS para la comunicación con el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "mi_token_secreto_123")
META_WHATSAPP_TOKEN = os.environ.get("META_WHATSAPP_TOKEN", "TU_TOKEN_DE_META")
META_PHONE_ID = os.environ.get("META_PHONE_ID", "TU_PHONE_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "TU_API_KEY_GEMINI")

# Configuración de Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://npkrraxozgrporgthxpd.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5wa3JyYXhvemdycG9yZ3RoeHBkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTY1MDksImV4cCI6MjEwMzA5MjUwOX0.JHwCPg9WccLa8VyFFd4BIW8QvMmL8E8oNqzRA_AbuzU")

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
        print("\n📥 NUEVO EVENTO DE WHATSAPP RECIBIDO:")
        
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
                            
                            # Procesamos con Gemini y Supabase en segundo plano
                            background_tasks.add_task(procesar_y_responder, numero_remitente, texto_recibido)

        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Error al recibir mensaje: {e}")
        return {"status": "error"}

async def procesar_y_responder(numero_telefono: str, mensaje_usuario: str):
    """
    Busca reglas en Supabase, procesa con Gemini, guarda historial y responde por WhatsApp.
    """
    print(f"🧠 Procesando respuesta para {numero_telefono}...")
    
    headers_supabase = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            # 1. Buscar si hay un agente configurado en Supabase
            res_agente = await client.get(
                f"{SUPABASE_URL}/rest/v1/agentes?select=*,clientes(*)&limit=1",
                headers=headers_supabase
            )
            
            contexto = "Eres un asistente virtual amable y servicial."
            handoff_words = ["humano", "asesor", "queja", "persona"]
            cliente_id = None
            
            if res_agente.status_code == 200 and len(res_agente.json()) > 0:
                agente_db = res_agente.json()[0]
                cliente_db = agente_db.get("clientes") or {}
                
                contexto = f"Eres {agente_db.get('nombre')}. Trabajas para {cliente_db.get('nombre', 'la empresa')}. Contexto: {cliente_db.get('contexto', '')}. Reglas: {agente_db.get('instrucciones', '')}"
                cliente_id = agente_db.get("cliente_id")
                
                if agente_db.get("handoff"):
                    handoff_words = [w.strip().lower() for w in agente_db.get("handoff").split(",")]

            # 2. Verificar si el usuario solicita atención humana (Handoff)
            requiere_humano = any(palabra in mensaje_usuario.lower() for palabra in handoff_words)

            # 3. Guardar el mensaje del usuario en Supabase
            await client.post(
                f"{SUPABASE_URL}/rest/v1/mensajes",
                headers=headers_supabase,
                json={
                    "cliente_id": cliente_id,
                    "telefono_usuario": numero_telefono,
                    "rol": "usuario",
                    "contenido": mensaje_usuario,
                    "requiere_humano": requiere_humano
                }
            )

            # 4. Generar respuesta con Gemini si no requiere humano inmediato
            if requiere_humano:
                texto_respuesta = "Entendido, he notificado a uno de nuestros asesores humanos para que continúe la atención contigo a la brevedad."
            else:
                # Actualizamos a la versión 3.5 Flash
                modelo = genai.GenerativeModel('gemini-3.5-flash')
                prompt = f"Instrucciones del bot: {contexto}\n\nCliente: {mensaje_usuario}\nAsistente:"
                respuesta_gemini = modelo.generate_content(prompt)
                texto_respuesta = respuesta_gemini.text

            print(f"🤖 Bot responde: {texto_respuesta}")

            # 5. Guardar la respuesta del bot en Supabase
            await client.post(
                f"{SUPABASE_URL}/rest/v1/mensajes",
                headers=headers_supabase,
                json={
                    "cliente_id": cliente_id,
                    "telefono_usuario": numero_telefono,
                    "rol": "bot",
                    "contenido": texto_respuesta,
                    "requiere_humano": requiere_humano
                }
            )

            # 6. Enviar mensaje de vuelta a WhatsApp
            await enviar_mensaje_whatsapp(numero_telefono, texto_respuesta)

        except Exception as e:
            print(f"❌ Error en procesar_y_responder: {e}")

async def enviar_mensaje_whatsapp(numero_destino: str, texto: str):
    """
    Usa la API de Meta para mandar el mensaje al celular del cliente.
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
