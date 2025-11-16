import os
import asyncio
import logging
import sys
from typing import Dict

from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from agents import Agent, Runner, SQLiteSession
from agents.mcp import MCPServerStdio


# ================== LOGGING ==================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class OrdersBot:
    """
    Bot Telegram che delega la logica ad un Agent OpenAI
    collegato ad un MCP server locale (ordini, listini, ecc.).
    """

    def __init__(self, mcp_server: MCPServerStdio) -> None:
        # Carica variabili da .env (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, ecc.)
        load_dotenv()

        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.telegram_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN non impostato nelle variabili d'ambiente")

        # Salvo il riferimento al server MCP (già aperto da main)
        self.mcp_server = mcp_server

        # Agent che si occupa di logica + tool MCP
        #
        # NOTA: qui NON usiamo più HostedMCPTool (server pubblico),
        # ma passiamo direttamente l'istanza MCPServerStdio in mcp_servers.
        self.agent = Agent(
            name="OrderAssistant",
            instructions=(
                "Sei un assistente per la gestione ordini via Telegram.\n"
                "- Parli in italiano.\n"
                "- PER USARE I SERVIZI REST devi usare il tool MCP 'call_rest_service' con "
                "il parametro `service_name` che corrisponde ESATTAMENTE a uno dei seguenti nomi:\n"
                "  * create_order  -> per inserire un nuovo ordine\n"
                "  * get_order     -> per leggere il dettaglio di un ordine\n"
                "  * get_orders    -> per leggere una lista di ordini\n"
                "  * get_price_list -> per leggere i prezzi\n"
                "- Prima di chiamare `call_rest_service`, se hai dubbi, usa il tool MCP "
                "  `list_rest_services` e scegli `service_name` dalla lista.\n"
                "- Quando l'utente chiede prezzi, listini, costi degli articoli, "
                "  DEVI chiamare `call_rest_service` con:\n"
                "    service_name = \"get_price_list\"\n"
                "    arguments.customer_code = codice cliente (se noto)\n"
                "    arguments.article_code  = codice articolo (se chiede un articolo specifico)\n"
                "- Se il risultato contiene prezzi generici (customer_id=null), "
                "- Se l'utente dice 'inserisci un ordine', mappa internamente questa intenzione "
                "  al servizio `create_order`.\n"
            ),

            # IMPORTANTISSIMO: qui agganciamo il server MCP locale
            mcp_servers=[self.mcp_server],
            # Se vuoi forzare SEMPRE l'uso di strumenti, puoi usare ModelSettings(tool_choice="required")
            # model_settings=ModelSettings(tool_choice="required"),
        )

        # Sessioni per memorizzare la conversazione (una per chat Telegram)
        self.sessions: Dict[int, SQLiteSession] = {}

        # Application di python-telegram-bot
        self.application: Application | None = None

    # ---------- utility sessione per chat ----------

    def _get_session(self, chat_id: int) -> SQLiteSession:
        """
        Ritorna (o crea) una sessione SQLite per quella chat.
        Così l'Agent si ricorda il contesto della conversazione.
        """
        if chat_id not in self.sessions:
            # usa un DB locale 'sessions.db'
            self.sessions[chat_id] = SQLiteSession(str(chat_id), "sessions.db")
        return self.sessions[chat_id]

    # ---------- handlers comandi ----------

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Gestisce /start"""
        text = (
            "Ciao! 👋 Sono il tuo assistente ordini.\n\n"
            "Puoi scrivere cose come:\n"
            "- *Inserisci un nuovo ordine per il cliente 1234 con consegna il 20/11*\n"
            "- *Mostrami lo stato dell'ordine 5678*\n"
            "- *Che prezzi abbiamo per l'articolo ABC123?*\n\n"
            "Scrivi in linguaggio naturale e penserò io a parlare con il gestionale. 😉"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Gestisce /help"""
        text = (
            "Posso aiutarti a:\n"
            "- Inserire nuovi ordini\n"
            "- Consultare lo stato avanzamento ordini\n"
            "- Recuperare informazioni commerciali (prezzi, sconti, disponibilità)\n\n"
            "Dimmi semplicemente cosa ti serve, ad esempio:\n"
            "*Vorrei inserire un ordine per il cliente 90017863 per 10 pezzi di MP002.*"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Resetta la memoria della conversazione per quella chat."""
        if not update.message:
            return

        chat_id = update.message.chat_id

        if chat_id in self.sessions:
            session = self.sessions[chat_id]
            # pulizia contenuto sessione
            await session.clear_session()
            del self.sessions[chat_id]

        await update.message.reply_text(
            "✅ Ho azzerato la memoria della conversazione per questa chat."
        )

    # ---------- handler messaggi normali ----------

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Gestisce tutti i messaggi di testo non comandi."""
        if not update.message or not update.message.text:
            return

        user_message = update.message.text.strip()
        chat_id = update.message.chat_id

        logger.info("Messaggio da %s: %s", chat_id, user_message)

        # Mostra "sta scrivendo..."
        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            session = self._get_session(chat_id)

            # Chiama l'Agent (che a sua volta userà MCP quando serve)
            result = await Runner.run(
                self.agent,
                input=user_message,
                session=session,
            )

            reply_text = result.final_output or "Non ho ottenuto alcuna risposta dall'agent."
            await update.message.reply_text(reply_text, parse_mode="Markdown")

        except Exception as e:
            logger.exception("Errore durante l'elaborazione del messaggio")
            await update.message.reply_text(
                "❌ Mi spiace, ho avuto un errore interno mentre processavo la tua richiesta."
            )

    # ---------- avvio bot ----------

    async def run(self) -> None:
        """Avvia il bot Telegram dentro un event loop già esistente (niente run_polling)."""
        logger.info("Inizializzo OrdersBot...")

        # Crea l'application se non esiste ancora
        if self.application is None:
            self.application = (
                Application.builder()
                .token(self.telegram_token)
                .build()
            )

            # Handler comandi
            self.application.add_handler(CommandHandler("start", self.start))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("reset", self.reset_command))

            # Handler messaggi di testo
            self.application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
            )

        app = self.application

        # Sequenza consigliata quando NON si usa run_polling
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        logger.info("Bot in esecuzione (polling)…")

        try:
            # Rimani in esecuzione finché il processo non viene interrotto (Ctrl+C)
            stop_event = asyncio.Event()
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Ricevuto segnale di stop, chiusura in corso…")
        finally:
            # Spegnimento ordinato
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            logger.info("Bot terminato correttamente.")


# ================== MAIN CON MCP LOCALE ==================

async def main() -> None:
    """
    - Legge .env (OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, ecc.)
    - Avvia il server MCP locale come processo figlio via stdio
      (esegue `python orders_mcp_server.py`)
    - Crea OrdersBot collegato al MCP server
    - Avvia il bot Telegram
    """
    load_dotenv()

    # Comando e script MCP (puoi personalizzarli da .env se vuoi)
    mcp_command = os.getenv("ORDERS_MCP_COMMAND", "python")
    mcp_script = os.getenv("ORDERS_MCP_SCRIPT", "orders_mcp_server.py")

    logger.info("Avvio MCPServerStdio: %s %s", mcp_command, mcp_script)

    # Il context manager avvia il processo MCP e lo chiude alla fine
    async with MCPServerStdio(
        name="Orders MCP Server",
        params={
            "command": mcp_command,
            "args": [mcp_script],
        },
        cache_tools_list=True,  # evita di richiedere i tool ad ogni run
    ) as orders_mcp_server:
        logger.info("MCP server avviato, creo il bot OrdersBot...")
        bot = OrdersBot(mcp_server=orders_mcp_server)

        try:
            await bot.run()
        except Exception:
            logger.exception("Il bot si è fermato a causa di un errore")
        finally:
            logger.info("Chiusura OrdersBot completata.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interruzione da tastiera, arresto bot...")
