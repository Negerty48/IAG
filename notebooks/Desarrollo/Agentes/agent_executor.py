"""Puente A2A: mantiene una sesión de chat por context_id y delega en el LLM de ONYX."""
import asyncio

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

# Importamos la lógica de nuestro agente táctico ONYX
from tactical_agent import SYSTEM, run_turn


class OnyxTacticalExecutor(AgentExecutor):
    def __init__(self) -> None:
        # context_id -> historial de mensajes (memoria de la conversación).
        self._sessions: dict[str, list] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        cid = context.context_id
        
        # Recuperamos o iniciamos el historial de esta sesión
        messages = self._sessions.setdefault(cid, [{"role": "system", "content": SYSTEM}])
        
        # Añadimos el nuevo mensaje del usuario extraído del contexto
        messages.append({"role": "user", "content": context.get_user_input()})

        # run_turn es síncrono (openai/httpx); fuera del event loop para no bloquearlo.
        reply = await asyncio.to_thread(run_turn, messages)

        # Enviamos la respuesta formateada de vuelta al cliente
        await event_queue.enqueue_event(new_agent_text_message(reply, context_id=cid))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel no soportado")