"""
Test de integración mínimo: verifica que todos los módulos críticos
se puedan importar sin errores (contratos, repositorios, servicios, routes).
"""
import sys
sys.path.insert(0, '.')

results = []

modules = [
    "app.core.config",
    "app.core.database",
    "app.core.security",
    "app.domain.models",
    "app.domain.models.conversation",
    "app.domain.models.document",
    "app.domain.exceptions",
    "app.schemas.google_chat",
    "app.schemas.conversation",
    "app.repositories.interfaces.conversation_repository",
    "app.repositories.interfaces.vector_repository",
    "app.services.interfaces.llm_service",
    "app.repositories.implementations.models_orm",
    "app.repositories.implementations.mysql_conversation_repository",
    "app.repositories.implementations.qdrant_vector_repository",
    "app.services.implementations.gemini_llm_service",
    "app.services.rag_service",
    "app.services.google_chat_service",
    "app.services.indexer_service",
    "app.api.dependencies",
    "app.api.v1.routes",
]

import importlib
errors = []
for mod in modules:
    try:
        importlib.import_module(mod)
        results.append(f"  [OK]    {mod}")
    except Exception as e:
        results.append(f"  [FAIL]  {mod}: {e}")
        errors.append(mod)

print("\n".join(results))
print()
if errors:
    print(f"FALLOS ({len(errors)}): {errors}")
    sys.exit(1)
else:
    print(f"Todos los módulos importaron correctamente ({len(modules)} total).")

