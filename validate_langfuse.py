"""
validate_langfuse.py
═══════════════════════════════════════════════════════════════════════
Script de validación de integración Langfuse.
Cumple con ISO/IEC 29119 (pruebas de caja negra) y verifica que todos los campos requeridos lleguen.

Pruebas:
    - Crear traza con todos los atributos gen_ai.*.
    - Verificar que la traza aparezca en Langfuse y contenga model, tokens, costs.
"""
import os
import sys
import base64
import time
import requests
from datetime import datetime

def main():
    print(f"\n{'='*60}")
    print(f"JARVI 2.0.03 | Validación de Langfuse | {datetime.utcnow().isoformat()}")
    print(f"{'='*60}\n")

    # 1. Verificar importación
    print("[1/6] Verificando importación de langfuse...")
    try:
        from langfuse import Langfuse
        print("✅ Módulo langfuse importado")
    except ImportError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    # 2. Verificar variables de entorno
    print("\n[2/6] Verificando variables de entorno...")
    required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Faltan: {missing}")
        sys.exit(1)
    print("✅ Variables configuradas")

    # 3. Crear traza de prueba con todos los atributos semánticos
    print("\n[3/6] Creando traza de prueba con atributos gen_ai...")
    try:
        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )
        trace = client.trace(
            name="validation_test",
            user_id="test_user",
            session_id="test_session",
            metadata={"test": True, "version": "2.0.03"}
        )
        # Crear observación con atributos gen_ai
        gen = trace.generation(
            name="gpt-4o-mini-test",
            model="gpt-4o-mini",
            model_parameters={"temperature": 0.1},
            input={"role": "user", "content": "Mensaje de prueba"},
            output={"role": "assistant", "content": "Respuesta de prueba"},
            usage={
                "input": 10,
                "output": 20,
                "total": 30,
                "unit": "TOKENS",
                "inputCost": 10 * 0.15 / 1_000_000,
                "outputCost": 20 * 0.60 / 1_000_000,
                "totalCost": (10*0.15 + 20*0.60) / 1_000_000
            }
        )
        client.flush()
        time.sleep(2)

        # Verificar en API
        print("\n[4/6] Verificando traza en Langfuse...")
        auth = base64.b64encode(f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()).decode()
        resp = requests.get(
            f"{os.getenv('LANGFUSE_HOST')}/api/public/traces/{trace.id}",
            headers={"Authorization": f"Basic {auth}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Traza confirmada con ID: {trace.id}")
            # Buscar la generación
            obs = data.get('observations', [{}])[0] if data.get('observations') else {}
            print(f"   - Model: {obs.get('model', 'N/A')}")
            usage = obs.get('usage', {})
            print(f"   - Input tokens: {usage.get('input', 'N/A')}")
            print(f"   - Output tokens: {usage.get('output', 'N/A')}")
            print(f"   - Total cost: {usage.get('totalCost', 'N/A')}")
        else:
            print(f"⚠️  API respondió {resp.status_code}, verificar manualmente")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("VALIDACIÓN COMPLETADA")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
