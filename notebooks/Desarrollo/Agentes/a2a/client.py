"""Cliente A2A interactivo (UX con rich): interfaz de analista táctico."""
import asyncio
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
    TextPart,
)
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

BASE = "http://127.0.0.1:9999"
console = Console()

def _extract(response) -> tuple[str, str | None]:
    """Extrae (texto, context_id) de la respuesta A2A."""
    result = response.root.result
    context_id = getattr(result, "context_id", None)
    parts = getattr(result, "parts", []) or []
    text = "".join(
        p.root.text for p in parts if getattr(p.root, "kind", None) == "text"
    )
    return text, context_id

async def chat() -> None:
    async with httpx.AsyncClient(timeout=60) as http:
        # Descubrimiento A2A
        with console.status("[cyan]Estableciendo conexión con el servidor táctico...", spinner="bouncingBar"):
            resolver = A2ACardResolver(httpx_client=http, base_url=BASE)
            card = await resolver.get_agent_card()
            client = A2AClient(httpx_client=http, agent_card=card)

        skills = ", ".join(s.name for s in card.skills)
        console.print(Panel(
            f"[bold]{card.description}[/bold]\n\n"
            f"[dim]Capacidades:[/dim] {skills}\n"
            f"[dim]Introduce el equipo o métrica a analizar. 'salir' para finalizar sesión.[/dim]",
            title=f"⚽  {card.name} - Terminal", border_style="green",
        ))

        context_id: str | None = None
        while True:
            user_text = (await asyncio.to_thread(
                Prompt.ask, "[bold cyan]Analista[/bold cyan]"
            )).strip()
            
            if user_text.lower() in {"salir", "exit", "quit"}:
                console.print("[dim]Cerrando sesión de análisis. 👋[/dim]")
                break
            if not user_text:
                continue

            message = Message(
                role=Role.user,
                parts=[Part(root=TextPart(text=user_text))],
                message_id=uuid4().hex,
                context_id=context_id,
            )
            request = SendMessageRequest(
                id=uuid4().hex,
                params=MessageSendParams(message=message),
            )

            with console.status("[green]Extrayendo líneas de juego y procesando métricas...", spinner="dots"):
                response = await client.send_message(request)

            reply, context_id = _extract(response)
            console.print(Panel(
                Markdown(reply), title="⬛ ONYX", border_style="cyan",
            ))

if __name__ == "__main__":
    try:
        asyncio.run(chat())
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Ejecución interrumpida 👋[/dim]")