from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
import httpx
import os

app = FastAPI(title="Webhook WhatsApp - Agencia de Chatbots")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "mi_token_secreto_123").strip().replace("\n", "").replace("\r", "")
META_WHATSAPP_TOKEN = os.environ.get("META_WHATSAPP_TOKEN", "TU_TOKEN_DE_META").strip().replace("\n", "").replace("\r", "")
META_PHONE_ID = os.environ.get("META_PHONE_ID", "TU_PHONE_ID").strip().replace("\n", "").replace("\r", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "TU_API_KEY_GEMINI").strip().replace("\n", "").replace("\r", "")

genai.configure(api_key=GEMINI_API_KEY)

@app.get("/webhook")
async def verificar_meta(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        print("✅ Webhook verificado por Meta exitosamente.")
        return Response(content=challenge, media_type="text/plain")
    
    raise HTTPException(status_code=403, detail="Token de verificación inválido")

@app.post("/webhook")
async def recibir_mensaje(request: Request):
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
                            print(f"\n📥 NUEVO MENSAJE DE WHATSAPP RECIBIDO DE: {numero_remitente}")
                            
                            texto_usuario = ""
                            if mensaje_info["type"] == "text":
                                texto_usuario = mensaje_info["text"]["body"]
                            elif mensaje_info["type"] == "audio":
                                texto_usuario = "[El usuario envió un mensaje de voz]"
                            elif mensaje_info["type"] == "image":
                                texto_usuario = mensaje_info["image"].get("caption", "[El usuario envió una imagen]")

                            print(f"💬 Texto: {texto_usuario}")

                            # Usamos el prefijo correcto que exige la librería actual
                            model = genai.GenerativeModel(
                                model_name="models/gemini-1.5-flash",
                                system_instruction="Eres un asistente virtual amable para una veterinaria llamada Veterinaria Gzz. Ayudas a los clientes a resolver dudas y agendar citas."
                            )

                            respuesta_ia = model.generate_content(texto_usuario)
                            texto_respuesta = respuesta_ia.text if respuesta_ia and respuesta_ia.text else "¡Hola! ¿En qué puedo ayudar a tu mascota hoy?"

                            print(f"🤖 Bot responde: {texto_respuesta}")

                            url_whatsapp = f"https://graph.facebook.com/v18.0/{META_PHONE_ID}/messages"
                            headers = {
                                "Authorization": f"Bearer {META_WHATSAPP_TOKEN}",
                                "Content-Type": "application/json"
                            }
                            payload = {
                                "messaging_product": "whatsapp",
                                "to": numero_remitente,
                                "type": "text",
                                "text": {"body": texto_respuesta}
                            }

                            async with httpx.AsyncClient() as client:
                                response = await client.post(url_whatsapp, headers=headers, json=payload, timeout=10.0)
                                if response.status_code != 200:
                                    print(f"❌ Error al enviar a WhatsApp: {response.text}")
                                else:
                                    print("✅ Mensaje respondido en WhatsApp exitosamente.")

        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Error crítico en webhook: {e}")
        return {"status": "error"}
