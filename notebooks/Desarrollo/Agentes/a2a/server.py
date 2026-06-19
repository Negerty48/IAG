"""Servidor A2A: publica la Agent Card y atiende peticiones del agente táctico ONYX."""
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from agent_executor import OnyxTacticalExecutor

# Definimos la herramienta/skill que el cliente verá que sabemos hacer
skill = AgentSkill(
    id="analyze_tactics",
    name="Análisis de rendimiento táctico",
    description="Devuelve métricas avanzadas y análisis de líneas de juego por visión artificial para un equipo de fútbol.",
    tags=["football", "tactics", "computer-vision", "sports-tech"],
    examples=[
        "Extrae las métricas de presión del Atlético de Madrid", 
        "¿Cuál fue la distancia entre líneas en el último partido?"
    ],
)

# La tarjeta de presentación de nuestro agente
agent_card = AgentCard(
    name="ONYX",
    description="Agente A2A especializado en análisis de rendimiento deportivo y métricas tácticas de fútbol.",
    url="http://127.0.0.1:9999/",
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[skill],
)

# Levantamos el manejador de peticiones enlazando nuestro ejecutor
handler = DefaultRequestHandler(
    agent_executor=OnyxTacticalExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2AStarletteApplication(agent_card=agent_card, http_handler=handler)

if __name__ == "__main__":
    print("Iniciando servidor A2A para ONYX (Análisis Táctico)...")
    uvicorn.run(app.build(), host="127.0.0.1", port=9999)