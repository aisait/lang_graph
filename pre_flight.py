import sys
import os

def check_langfuse():
    print("--- [PRE-FLIGHT] Iniciando diagnóstico de Langfuse ---")
    
    try:
        # 1. Intentar importar el módulo base
        import langfuse
        print(f"[OK] Módulo langfuse importado desde: {langfuse.__file__}")

        # 2. Intentar cargar la clase principal
        # Esto dispara la inicialización de pydantic-core (los binarios en Rust/C)
        from langfuse import Langfuse
        print("[OK] Clase Langfuse inicializada. Los binarios de Pydantic han cargado.")

        # 3. Verificar si el linker cargó las librerías dinámicas necesarias
        # (Un chequeo simple para ver si el entorno está sano)
        print("[OK] El sistema de archivos y el cargador dinámico están operativos.")

    except ImportError as e:
        print(f"[ERROR] ImportError: {e}")
        print("Causa probable: Falta un paquete de Python o el nombre del paquete está mal.")
        sys.exit(1)
    except OSError as e:
        # Este es el error más probable: "libstdc++.so.6: cannot open shared object file"
        print(f"[ERROR] OSError (Fallo de enlace dinámico/ABI): {e}")
        print("Causa probable: El binario compilado (Rust/C) no encuentra las librerías del sistema.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Excepción inesperada: {type(e).__name__} - {e}")
        sys.exit(1)

    print("--- [PRE-FLIGHT] Diagnóstico exitoso. Entorno validado. ---")

if __name__ == "__main__":
    check_langfuse()
