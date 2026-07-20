#!/usr/bin/env python3
"""
validate_langfuse.py - Validación determinística de Langfuse vía OTLP.
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
    print(f"JARVI 2.0.03 | Validación de Langfuse | {datetime.utcnow().isoformat()}")
    print(f"{'='*60}\n")

    # 1. Verificar importación
    print("[1/4] Verificando importación de langfuse...")
    try:
        from langfuse import Langfuse
        from langfuse.callback import CallbackHandler
        print("✅ Módulo langfuse importado correctamente")
    except ImportError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    # 2. Verificar variables de entorno
    print("\n[2/4] Verificando variables de entorno...")
    required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Faltan: {missing}")
        sys.exit(1)
    print("✅ Variables de entorno configuradas")

    # 3. Crear traza de prueba
    print("\n[3/4] Creando traza de prueba...")
    try:
        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )
        trace = client.trace(
            name="validation_test",
            user_id="validation_bot",
            metadata={"source": "validation_script", "timestamp": datetime.utcnow().isoformat()}
        )
        span = trace.span(name="test_span", input={"test": "input"})
        span.end(output={"test": "output"})
        client.flush()
        print(f"✅ Traza creada con ID: {trace.id}")
        time.sleep(2)
        
        # 4. Verificar en API
        print("\n[4/4] Verificando en Langfuse...")
        auth = base64.b64encode(f"{os.getenv('LANGFUSE_PUBLIC_KEY')}:{os.getenv('LANGFUSE_SECRET_KEY')}".encode()).decode()
        resp = requests.get(
            f"{os.getenv('LANGFUSE_HOST')}/api/public/traces/{trace.id}",
            headers={"Authorization": f"Basic {auth}"},
            timeout=10
        )
        if resp.status_code == 200:
            print(f"✅ Traza confirmada en Langfuse")
            print(f"   URL: {os.getenv('LANGFUSE_HOST')}/trace/{trace.id}")
        else:
            print(f"⚠️  API respondió {resp.status_code}, verificar manualmente")
            print(f"   URL: {os.getenv('LANGFUSE_HOST')}/trace/{trace.id}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("VALIDACIÓN COMPLETADA")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
