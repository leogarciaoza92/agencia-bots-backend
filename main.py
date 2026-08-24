from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
import httpx # Para peticiones HTTP a WhatsApp y Supabase
import os
import json
import base64 # NUEVO: Para enviar audios a Gemini

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
                        
                        # MODIFICACIÓN: Aceptamos tanto 'text' como 'audio'
                        if mensaje_info["type"] in ["text", "audio"]:
                            
                            # Procesamos con Gemini y Supabase en segundo plano pasándole TODO el mensaje
                            background_tasks.add_task(procesar_y_responder, numero_remitente, mensaje_info)

        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Error al recibir mensaje: {e}")
        return {"status": "error"}

def agendar_cita(fecha: str, hora: str) -> str:
    """
    Agenda una cita en el sistema/calendario para un paciente o cliente.
    Usa esta función ÚNICAMENTE cuando el usuario confirme que quiere agendar un día y hora específicos.
    """
    print(f"📅 [ACCIÓN REAL EJECUTADA] Bloqueando espacio en calendario para el {fecha} a las {hora}")
    # En el futuro, aquí conectarías la API de Google Calendar. 
    # Por ahora, le devolvemos el éxito a Gemini para que continúe la charla.
    return f"ÉXITO: La cita ha sido registrada y agendada correctamente en el sistema para el {fecha} a las {hora}."


async def procesar_y_responder(numero_telefono: str, mensaje_info: dict):
    """
    Busca reglas en Supabase, procesa AUDIO/TEXTO con Gemini (con Function Calling), guarda y responde.
    """
    print(f"🧠 Procesando respuesta para {numero_telefono}...")
    
    headers_supabase = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            # 1. Extraer el contenido según si es texto o audio
            tipo_mensaje = mensaje_info["type"]
            mensaje_usuario_texto = "[Audio Recibido]"
            datos_audio_base64 = None

            if tipo_mensaje == "text":
                mensaje_usuario_texto = mensaje_info["text"]["body"]
            elif tipo_mensaje == "audio":
                print("🎙️ Audio detectado. Descargando de WhatsApp...")
                media_id = mensaje_info["audio"]["id"]
                headers_meta = {"Authorization": f"Bearer {META_WHATSAPP_TOKEN}"}
                
                # Obtenemos la URL del archivo
                res_url = await client.get(f"https://graph.facebook.com/v19.0/{media_id}", headers=headers_meta)
                media_url = res_url.json().get("url")
                
                # Descargamos los bytes del audio y los preparamos para Gemini
                res_media = await client.get(media_url, headers=headers_meta)
                datos_audio_base64 = base64.b64encode(res_media.content).decode("utf-8")
                mensaje_usuario_texto = "[El usuario ha enviado una nota de voz, escúchala y respóndele]"


            # 2. Buscar si hay un agente configurado en Supabase
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
                
                contexto = f"Eres {agente_db.get('nombre')}. Trabajas para {cliente_db.get('nombre', 'la empresa')}. Contexto: {cliente_db.get('contexto', '')}. Reglas: {agente_db.get('instrucciones', '')}. INFORMACIÓN EXTRA (Documentos/Precios): {agente_db.get('conocimiento_extra', '')}"
                cliente_id = agente_db.get("cliente_id")
                
                if agente_db.get("handoff"):
                    handoff_words = [w.strip().lower() for w in agente_db.get("handoff").split(",")]

            # 3. Verificar Handoff
            requiere_humano = any(palabra in mensaje_usuario_texto.lower() for palabra in handoff_words)

            # 4. Guardar el mensaje del usuario en Supabase
            await client.post(
                f"{SUPABASE_URL}/rest/v1/mensajes",
                headers=headers_supabase,
                json={
                    "cliente_id": cliente_id,
                    "telefono_usuario": numero_telefono,
                    "rol": "usuario",
                    "contenido": mensaje_usuario_texto,
                    "requiere_humano": requiere_humano
                }
            )

            # 5. Generar respuesta con Gemini (Soporte Audio y Funciones)
            if requiere_humano:
                texto_respuesta = "Entendido, he notificado a uno de nuestros asesores humanos para que continúe la atención contigo a la brevedad."
            else:
                modelo = genai.GenerativeModel(
                    model_name='gemini-3.5-flash',
                    system_instruction=contexto,
                    tools=[agendar_cita] # Aquí le damos el "poder" de agendar
                )
                
                # Iniciamos un chat que ejecutará funciones automáticamente si es necesario
                chat = modelo.start_chat(enable_automatic_function_calling=True)
                
                if tipo_mensaje == "audio" and datos_audio_base64:
                    # Le enviamos el audio como "inline_data"
                    contenido_a_enviar = [{"mime_type": "audio/ogg", "data": datos_audio_base64}]
                    respuesta_gemini = chat.send_message(contenido_a_enviar)
                else:
                    respuesta_gemini = chat.send_message(mensaje_usuario_texto)
                
                texto_respuesta = respuesta_gemini.text

            print(f"🤖 Bot responde: {texto_respuesta}")

            # 6. Guardar la respuesta del bot
