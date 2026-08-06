"""
Windows-only fix: some of these libraries crash with a native access
violation if loaded in a certain order (a DLL/native-library conflict
between Chroma's onnxruntime, Google's grpc/protobuf stack, and Groq's
client). Importing them here first, in this specific proven-safe order,
before anything else in the app touches them, avoids the crash.

This must be the very first import in every real entry point (main.py,
test.py) — before any of our own project modules are imported.
"""
import langchain_text_splitters  # noqa: F401
import github  # noqa: F401
import langchain_chroma  # noqa: F401
import langchain_google_genai  # noqa: F401
import langchain_groq  # noqa: F401