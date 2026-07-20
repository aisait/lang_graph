# validate_langfuse.py
import os
import asyncio
from langfuse import Langfuse

async def validate():
    lf = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST")
    )
    trace = lf.trace(name="validation_test", user_id="test_user")
    span = trace.span(name="test_span", input={"test": "input"})
    span.end(output={"test": "output"})
    lf.flush()
    print(f"✅ Traza creada: {trace.id}")

asyncio.run(validate())
