import base64
import json
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def procesar_imagen_factura(base64_image: str) -> dict:
    """Utiliza GPT-4o-mini para extraer datos estructurados de la factura en Base64[cite: 67]."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": "Analiza esta factura de electricidad de Guatemala. Extrae en formato JSON estricto: 1. 'empresa_electrica' (Busca EEGSA o ENERGUATE), 2. 'consumo_kwh' (sólo el número), 3. 'monto_factura' (sólo el número en Quetzales). Si no detectas un dato, asigna null. [cite: 68, 69]"
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)
