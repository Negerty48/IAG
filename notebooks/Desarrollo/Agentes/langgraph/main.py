import os
import re
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from agent import builder
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import ToolMessage

load_dotenv()

memoria_telegram = MemorySaver()

agente_telegram = builder.compile(
    checkpointer=memoria_telegram,
    interrupt_before=["subflujo_stats"]
)

def formatear(texto: str) -> str:
    texto = re.sub(r'#+\s*', '', texto)
    texto = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', texto)
    return texto

async def procesar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_text = update.message.text
    nombre_usuario = update.message.chat.first_name

    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        config = {"configurable": {"thread_id": str(chat_id)}}
        estado = await agente_telegram.aget_state(config)
        
        # 2. EVALUAMOS SI ESTABA PAUSADO ANTES DE ENTRAR A LAS ESTADÍSTICAS
        if estado.next and "subflujo_stats" in estado.next:
            # CASO A: SI EL USUARIO APRUEBA
            if user_text.lower() in ["sí", "si", "dale", "ok", "yes", "autorizo"]:
                await update.message.reply_text("⏳ Autorizado. Onyx está extrayendo los datos de StatsBomb...")
                resultado = await agente_telegram.ainvoke(None, config=config)
                
            # CASO B: SI EL USUARIO DENIEGA
            else:
                await update.message.reply_text("❌ Operación cancelada. El agente no buscará estadísticas.")
                
                # Falsificamos la salida del subgrafo paralelo para que Onyx sepa que se canceló
                await agente_telegram.aupdate_state(
                    config, 
                    {"contexto_paralelo": ["Operación cancelada explícitamente por el analista."]},
                    as_node="subflujo_stats"
                )
                
                # Reanudamos el agente para que procese la cancelación en silencio
                resultado = await agente_telegram.ainvoke(None, config=config)
                return
            
        # 3. FLUJO NORMAL (Si no estaba pausado)
        else:
            inputs = {"messages": [("user", user_text)]}
            resultado = await agente_telegram.ainvoke(inputs, config=config)

        # 4. VERIFICAMOS SI SE HA PAUSADO TRAS LA ÚLTIMA ACCIÓN
        nuevo_estado = await agente_telegram.aget_state(config)
        if nuevo_estado.next and "subflujo_stats" in nuevo_estado.next:
            
            # Leemos la memoria interna de Onyx para saber qué va a buscar
            match = nuevo_estado.values.get("match_id", "Desconocido")
            jugador = nuevo_estado.values.get("jugador_objetivo")
            
            peticion = f"Partido ID: {match}"
            if jugador:
                peticion += f" | Jugador: {jugador}"
            
            mensaje_hitl = (
                f"⚠️ <b>Control Manual Requerido:</b>\n"
                f"El agente va a ejecutar consultas masivas para:\n<code>{peticion}</code>\n"
                f"¿Autorizas la ejecución? (sí / no)"
            )
            await update.message.reply_text(mensaje_hitl, parse_mode='HTML')
            return

        # 5. RESPUESTA FINAL CON MANEJO DE LÍMITES DE TELEGRAM
        respuesta_agente = resultado["messages"][-1].content
        
        if not respuesta_agente:
            respuesta_agente = "Operación procesada, pero no hay respuesta de texto."
            
        texto_limpio = formatear(respuesta_agente)
        
        # División por límite de 4000 caracteres
        LIMITE_TELEGRAM = 4000
        if len(texto_limpio) > LIMITE_TELEGRAM:
            parrafos = texto_limpio.split('\n\n')
            mensaje_actual = ""
            for parrafo in parrafos:
                if len(parrafo) > LIMITE_TELEGRAM:
                    parrafo = parrafo[:LIMITE_TELEGRAM - 100] + "... [Continúa]"
                if len(mensaje_actual) + len(parrafo) < LIMITE_TELEGRAM:
                    mensaje_actual += parrafo + "\n\n"
                else:
                    try:
                        await update.message.reply_text(mensaje_actual, parse_mode='HTML')
                    except Exception:
                        await update.message.reply_text(mensaje_actual)
                    mensaje_actual = parrafo + "\n\n"
            if mensaje_actual.strip():
                try:
                    await update.message.reply_text(mensaje_actual, parse_mode='HTML')
                except Exception:
                    await update.message.reply_text(mensaje_actual)
        else:
            await update.message.reply_text(texto_limpio, parse_mode='HTML')
            
        print(f"✅ Respuesta enviada a {nombre_usuario}")
        
    except Exception as e:
        print(f"❌ Error crítico: {e}")
        await update.message.reply_text("Ups, fallo técnico en la infraestructura de Onyx. ¿Me lo repites?")

if __name__ == '__main__':
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("❌ Error: Falta el TELEGRAM_TOKEN en el archivo .env")
        exit(1)

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_mensaje))
    
    print("🤖 ScoutAgent (Fan-Out Estructural) en producción escuchando a Telegram...")
    app.run_polling()