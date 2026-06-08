import os
import re
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from agent import builder
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()

# Instanciamos el guardado de memoria. Esto es lo que permite que el bot recuerde la conversación de cada usuario de forma independiente.
memoria_telegram = MemorySaver()

# Compilamos el 'builder' de agent.py inyectandole explícitamente la memoria.
agente_telegram = builder.compile(checkpointer=memoria_telegram)

# FUNCIONES AUXILIARES
def formatear(texto: str) -> str:
    """
    Adapta el texto generado por el LLM (Markdown) al formato que acepta Telegram (HTML).
    """
    texto = re.sub(r'#+\s*', '', texto)
    texto = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', texto)
    return texto

# LÓGICA PRINCIPAL DEL BOT (HANDLER)
async def procesar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Esta función se ejecuta cada vez que el bot recibe un mensaje de texto.
    """
    # Extraemos los datos útiles del mensaje entrante
    chat_id = update.message.chat_id
    user_text = update.message.text
    nombre_usuario = update.message.chat.first_name

    # Muestra el estado "Escribiendo..." en la app de Telegram del usuario
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        # Configuramos el hilo usando el chat_id como identificador único.        
        config = {"configurable": {"thread_id": str(chat_id)}}
        
        # Estructuramos el mensaje del usuario en el formato que espera nuestro StateGraph
        inputs = {"messages": [("user", user_text)]}

        # Llamamos al agente pasándole el input y la configuración de memoria
        resultado = await agente_telegram.ainvoke(inputs, config=config)
        respuesta_agente = resultado["messages"][-1].content

        # Limpiamos el texto y lo enviamos de vuelta al chat de Telegram indicando que use parseo HTML
        texto_limpio = formatear(respuesta_agente)
        await update.message.reply_text(texto_limpio, parse_mode='HTML')
        print(f"✅ Respuesta enviada a {nombre_usuario}")
        
    except Exception as e:
        # Capturador de errores por si falla la API de OpenAI, LangGraph o la de StatsBomb
        print(f"❌ Error: {e}")
        await update.message.reply_text("Ups, fallo técnico en el análisis. ¿Me lo repites?")

# INICIALIZACIÓN DEL SERVIDOR DE TELEGRAM
if __name__ == '__main__':
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("❌ Error: Falta el TELEGRAM_TOKEN en el archivo .env")
        exit(1)

    app = Application.builder().token(token).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_mensaje))
    
    print("🤖 ScoutAgent (LangGraph) en producción escuchando a Telegram...")

    app.run_polling()