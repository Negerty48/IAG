"""Agente conversacional ONYX: LLM de Azure + tool-calling táctico."""
import json
import os
import sys

from dotenv import load_dotenv
from openai import AzureOpenAI

from tactical_service import get_tactical_metrics

load_dotenv()

# Instanciamos el cliente nativo usando las variables de tu .env
_client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
)
_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

SYSTEM = (
    "Eres ONYX, un asistente experto en analizar y resolver peticiones de rendimiento táctico "
    "de fútbol usando visión artificial. Cuando el usuario pregunte por un equipo, usa la "
    "herramienta get_tactical_metrics para extraer los datos tácticos en tiempo real. "
    "Reporta las métricas exactamente como las devuelve la herramienta, sin inventar datos. "
    "Responde de forma concisa, técnica, estructurada y mantén el contexto de la conversación."
)

# Definimos el esquema de la herramienta para que el LLM sepa cómo llamarla
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_tactical_metrics",
        "description": "Obtiene las métricas tácticas y el análisis de líneas de juego de un equipo de fútbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Nombre del equipo de fútbol"},
            },
            "required": ["team"],
        },
    },
}]

def run_turn(messages: list) -> str:
    """Ejecuta un turno de chat sobre `messages` (mutado in situ). Resuelve las
    llamadas a herramientas y devuelve el texto final de ONYX."""
    while True:
        resp = _client.chat.completions.create(
            model=_DEPLOYMENT,
            messages=messages,
            tools=TOOLS,
            max_tokens=400,
        )
        msg = resp.choices[0].message

        assistant = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant["tool_calls"] = [{
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            } for tc in msg.tool_calls]
        messages.append(assistant)

        # Si el modelo no necesita herramientas, devuelve la respuesta de texto
        if not msg.tool_calls:
            return msg.content or ""

        # Si el modelo solicita una herramienta, la ejecutamos y retroalimentamos el bucle
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            result = get_tactical_metrics(args.get("team", ""))
            
            # Imprimimos la traza por consola para auditoría y debug
            print(
                f"[DEBUG][tool] get_tactical_metrics({args!r}) -> "
                f"{json.dumps(result, ensure_ascii=False)}",
                file=sys.stderr, flush=True,
            )
            
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

if __name__ == "__main__":
    # Prueba local sin necesidad del servidor A2A
    history = [{"role": "system", "content": SYSTEM}]
    history.append({"role": "user", "content": "Analiza las líneas de juego del Atlético de Madrid."})
    print(run_turn(history))