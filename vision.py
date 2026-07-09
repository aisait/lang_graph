"""
vision.py - Procesamiento de imágenes para extraer datos de facturas eléctricas.
Usa OpenAI GPT-4o-mini con visión.
"""
import os
import base64
import json
import requests
from openai import OpenAI

def _obtener_cliente_openai() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY_1") or os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_2")
    if not api_key:
        raise RuntimeError("No se encontró ninguna API Key de OpenAI.")
    return OpenAI(api_key=api_key)

def descargar_imagen_desde_url(url: str) -> bytes:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content

def procesar_imagen_factura(base64_image: str) -> dict:
    client = _obtener_cliente_openai()
    respuesta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Analiza esta factura de electricidad de Guatemala. "
                            "Extrae en formato JSON estricto: "
                            "1. 'empresa_electrica' (Busca EEGSA o ENERGUATE), "
                            "2. 'consumo_kwh' (sólo el número), "
                            "3. 'monto_factura' (sólo el número en Quetzales). "
                            "Si no detectas un dato, asigna null."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        response_format={"type": "json_object"}
    )
    contenido = respuesta.choices[0].message.content
    datos = json.loads(contenido)
    return {
        "empresa_electrica": datos.get("empresa_electrica", None),
        "consumo_kwh": datos.get("consumo_kwh", None),
        "monto_factura": datos.get("monto_factura", None)
    }

def procesar_imagen_desde_url(url: str) -> dict:
    img_bytes = descargar_imagen_desde_url(url)
    base64_img = base64.b64encode(img_bytes).decode('utf-8')
    return procesar_imagen_factura(base64_img)
