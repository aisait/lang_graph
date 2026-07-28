#!/usr/bin/env python3
import os
from langfuse import Langfuse

def main():
    print("🔍 Verificando SDK de Langfuse...")
    try:
        client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST")
        )
        if hasattr(client, 'trace'):
            print("✅ SDK compatible (método trace disponible)")
        else:
            print("❌ SDK ANTIGUO (no tiene método trace)")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
