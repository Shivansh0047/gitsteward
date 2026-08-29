"""
Windows-only fix: some of these libraries crash with a native access
violation if loaded in a certain order (a DLL/native-library conflict
between Chroma's onnxruntime, Google's grpc/protobuf stack, and Groq's
client). Importing them here first, in this specific proven-safe order,
before anything else in the app touches them, avoids the crash. This must be the very first import in every real entry point.

noqa: F401 -> tells Python linting tools like Flake8 and Ruff to ignore an "imported but unused" module warning on that specific line
"""
import langchain_text_splitters  # noqa: F401
import github  # noqa: F401
import langchain_google_genai  # noqa: F401
import langchain_groq  # noqa: F401