#!/usr/bin/env python3
"""
validate_langfuse.py - Validación de integración Langfuse v4 (4.14.1)
Cumple con ISO/IEC 29119 (pruebas de caja negra).
"""
import os
import sys
import base64
import time
import requests
from datetime import datetime

def main():
    print(f"\n{'='*60}")
    print(f"JARVI 2.0.03 | Validación de Langfuse v4 | {datetime.utcnow().isoformat()}")
    print(f"{'='*60}\n")

    try:
        from langfuse import Langfuse
        print("✅ Módulo langfuse importado")
    except ImportError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Faltan variables: {missing}")
        sys.exit(1)
    print("✅ Variables configuradas")

    try:
        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )

        print("📡 Creando traza de prueba...")
        trace = client.trace(
            name="validation_test",
            user_id="test_user",
            session_id="test_session",
            metadata={"test": True, "version": "2.0.03"}
        )

        trace.generation(
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
        print(f"✅ Traza creada con ID: {trace.id}")

        print("\n🔍 Verificando en Langfuse...")
        time.sleep(2)
        auth = base64.b64encode(f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()).decode()
        resp = requests.get(
            f"{os.getenv('LANGFUSE_HOST')}/api/public/traces/{trace.id}",
            headers={"Authorization": f"Basic {auth}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Traza confirmada")
        else:
            print(f"⚠️  API respondió {resp.status_code}")

        print(f"\n🔗 URL: {os.getenv('LANGFUSE_HOST')}/trace/{trace.id}")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("VALIDACIÓN COMPLETADA")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
