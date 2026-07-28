#!/usr/bin/env python3
# test_langfuse.py - Validación de SDK de Langfuse

import os
import sys

def main():
    print("🔍 Probando SDK de Langfuse...")
    try:
        from langfuse import Langfuse
        print("✅ Módulo importado")

        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )

        trace = client.trace(name="test_sdk", user_id="test_user", input={"msg": "hello"})
        print(f"✅ Traza creada: {trace.id}")

        trace.generation(
            name="test_generation",
            model="gpt-4",
            output={"response": "ok"},
            usage={"input": 10, "output": 20, "total": 30}
        )
        print("✅ Generación creada")

        client.flush()
        print("✅ Flush completado")
        print("🎉 SDK funciona correctamente")
        return 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
