import logging
import json
import os
import io
import time
import asyncio
import zipfile
import subprocess
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

# Читаем ключи из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8994105870:AAGdJsv0GkpZfXUnOAf9YQ5UUphVvZFzBOs")
GEMINI_KEY = os.getenv("GEMINI_KEY", "")

PORT = int(os.getenv("PORT", 8080))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JAR_SIGNER = os.path.join(BASE_DIR, "uber-apk-signer.jar")
BASE_APK = os.path.join(BASE_DIR, "love_embed.apk")

AVAILABLE_MODELS = {
    "gemini-2.5-flash": "⚡ Gemini 2.5 Flash (Стабильная и быстрая)",
    "gemini-2.5-pro": "🧠 Gemini 2.5 Pro (Максимальный интеллект)"
}

user_projects = {}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ВЕБ-СЕРВЕР ЗАЩИТЫ ОТ СНА ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Game Bot 24/7 is LIVE and HEALTHY!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_http_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    logger.info(f"Health check HTTP server running on port {PORT}")
    server.serve_forever()

def self_ping_loop():
    time.sleep(30)
    while True:
        try:
            url = RENDER_EXTERNAL_URL if RENDER_EXTERNAL_URL else f"http://127.0.0.1:{PORT}"
            requests.get(url, timeout=10)
        except Exception:
            pass
        time.sleep(480)

# --- ПАНЕЛЬ КНОПОК ---
PERMANENT_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🎮 Выбрать готовую игру"), KeyboardButton("🆕 Новая игра")],
        [KeyboardButton("📱 Собрать игру в APK"), KeyboardButton("✏️ Улучшить / Изменить")],
        [KeyboardButton("🤖 Выбрать модель ИИ"), KeyboardButton("❓ Помощь")]
    ],
    resize_keyboard=True
)

SYSTEM_PROMPT = """
Ты — элитный разработчик мобильных 2D и 3D игр, а также полезных приложений.
Ты умеешь создавать игры с нуля и ДОРАБАТЫВАТЬ существующие проекты.

ВОЗМОЖНОСТИ ПО ГРАФИКЕ:
1. 2D игры: яркая и плавная 2D графика (Canvas 2D / Love2D Graphics) со спецэффектами (частицы, тени, анимации).
2. 3D игры: полноценная трехмерная графика через WebGL / Three.js (3D трассы, машинки, 3D кубы, освещение, камеры от третьего лица).
3. Приложения и утилиты: красивые мобильные интерфейсы со стилями, кнопками и сохранением состояния.

ТРЕБОВАНИЯ К КОДУ:
1) HTML5-код (версия для мгновенного теста):
   - Если игра 3D — подключай библиотеку Three.js через CDN (<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>) и делай полноценный 3D мир с камерой, текстурами и освещением.
   - Если игра 2D или приложение — делай нативно на HTML5 Canvas или стильном CSS/JS.
   - Полная адаптация под экран смартфона (сенсорные джойстики, кнопки на экране, тач-события).

2) Lua-код (версия для Love2D APK):
   - Оптимизированный код Love2D (main.lua) с отрисовкой через love.draw(), love.update(dt), touch/mouse событиями.

ФОРМАТ ВЫВОДА (ОБЯЗАТЕЛЬНО В БЛОКАХ):
```html
<!-- полный рабочий HTML5/3D/2D код -->
```
```lua
-- полный рабочий Love2D код
```
"""

def generate_or_update_game(user_id: int, user_prompt: str, is_update: bool = False) -> tuple:
    user_data = user_projects.get(user_id, {})
    current_lua = user_data.get("lua", "")
    current_html = user_data.get("html", "")
    selected_model = user_data.get("model", "gemini-2.5-flash")
    
    if is_update and (current_lua or current_html):
        prompt_context = (
            f"{SYSTEM_PROMPT}\n\n"
            f"ТЕКУЩИЙ КОД ИГРЫ (HTML):\n```html\n{current_html}\n```\n\n"
            f"ТЕКУЩИЙ КОД ИГРЫ (LUA):\n```lua\n{current_lua}\n```\n\n"
            f"ЗАПРОС НА ДОРАБОТКУ:\n{user_prompt}\n\n"
            f"Внеси запрошенные изменения и выдай ПОЛНЫЙ исправленный код в блоках ```html ... ``` и ```lua ... ```."
        )
    else:
        prompt_context = f"{SYSTEM_PROMPT}\n\nПользователь создает НОВУЮ 2D/3D игру или приложение:\n{user_prompt}"

    if not GEMINI_KEY:
        raise Exception("API ключ Gemini не настроен!")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={GEMINI_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt_context}]}
        ]
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=90)
    if response.status_code != 200:
        raise Exception(f"Ошибка Gemini API: {response.status_code} {response.text}")
    
    data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception("Не удалось распарсить ответ Gemini")

    new_lua = ""
    new_html = ""

    if "```html" in text:
        new_html = text.split("```html")[1].split("```")[0].strip()

    if "```lua" in text:
        new_lua = text.split("```lua")[1].split("```")[0].strip()

    if new_lua or new_html:
        user_projects[user_id]["lua"] = new_lua if new_lua else current_lua
        user_projects[user_id]["html"] = new_html if new_html else current_html
        user_projects[user_id]["awaiting_fix"] = False

    return user_projects[user_id]["html"], user_projects[user_id]["lua"]

def build_apk(lua_code: str, user_id: int) -> str:
    love_bytes = io.BytesIO()
    with zipfile.ZipFile(love_bytes, 'w', zipfile.ZIP_DEFLATED) as z_love:
        z_love.writestr('main.lua', lua_code)
    game_love_data = love_bytes.getvalue()

    out_apk_path = os.path.join(BASE_DIR, f"game_{user_id}.apk")
    if os.path.exists(out_apk_path):
        try: os.remove(out_apk_path)
        except: pass

    with zipfile.ZipFile(BASE_APK, 'r') as zin:
        with zipfile.ZipFile(out_apk_path, 'w') as zout:
            for item in zin.infolist():
                if not item.filename.startswith('META-INF/'):
                    buffer = zin.read(item.filename)
                    zout.writestr(item, buffer)
            zout.writestr('assets/game.love', game_love_data)

    cmd = ["java", "-jar", JAR_SIGNER, "-a", out_apk_path, "--overwrite", "--allowResign"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        logger.error(f"Sign error: {p.stderr}")
        raise Exception("Не удалось подписать APK-файл")
        
    return out_apk_path

# Инлайн-кнопки под готовым тестом
def get_game_actions_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 Игра нравится! Собрать в APK", callback_data="build_apk_now")],
        [InlineKeyboardButton("✏️ Улучшить / Изменить", callback_data="improve_game")],
        [InlineKeyboardButton("🆕 Выбрать другую игру", callback_data="new_game")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_preset_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("🏎 3D Гонки (Three.js)", callback_data="preset_3d_racing")],
        [InlineKeyboardButton("🌌 3D Космос / Полеты", callback_data="preset_3d_space")],
        [InlineKeyboardButton("🐱 2D Кликер с котиком", callback_data="preset_cat_clicker")],
        [InlineKeyboardButton("🍬 2D Три в ряд", callback_data="preset_match3")],
        [InlineKeyboardButton("🐍 2D Веселая Змейка", callback_data="preset_snake")],
        [InlineKeyboardButton("✨ Написать свою 2D/3D идею", callback_data="custom_game")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_models_inline_keyboard(user_id: int):
    current_model = user_projects.get(user_id, {}).get("model", "gemini-2.5-flash")
    keyboard = []
    for model_id, name in AVAILABLE_MODELS.items():
        prefix = "✅ " if model_id == current_model else "⚪ "
        keyboard.append([InlineKeyboardButton(f"{prefix}{name}", callback_data=f"set_model_{model_id}")])
    return InlineKeyboardMarkup(keyboard)

async def post_init(application: Application):
    bot_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("apk", "Собрать текущую игру в APK"),
        BotCommand("models", "Выбрать модель ИИ"),
        BotCommand("menu", "Список готовых игр"),
        BotCommand("new", "Создать новую игру"),
        BotCommand("fix", "Улучшить игру"),
        BotCommand("help", "Помощь")
    ]
    await application.bot.set_my_commands(bot_commands)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_projects:
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": "gemini-2.5-flash"}
    
    text = (
        "👋 **Здравствуйте! Я создаю 2D и 3D игры и программы для телефона.**\n\n"
        "🎮 **Поддержка 3D:** трёхмерная графика, освещение, вид от третьего лица.\n"
        "🎨 **Поддержка 2D:** красочные аркады, головоломки, кликеры.\n\n"
        "👇 Выберите готовую игру или напишите любую свою задумку:"
    )
    await update.message.reply_text(text, reply_markup=PERMANENT_KEYBOARD, parse_mode="Markdown")
    await update.message.reply_text("Выберите игру из списка:", reply_markup=get_preset_inline_keyboard())

async def process_apk_build(message, user_id: int):
    user_data = user_projects.get(user_id, {})
    lua_code = user_data.get("lua", "")
    
    if not lua_code:
        await message.reply_text(
            "⚠️ Сначала создайте игру, а затем нажмите кнопку сборки APK!",
            reply_markup=PERMANENT_KEYBOARD
        )
        return

    status_msg = await message.reply_text("⚙️ **Компилирую и подписываю APK для Android...**\nПожалуйста, подождите...")
    
    try:
        loop = asyncio.get_event_loop()
        apk_file_path = await loop.run_in_executor(None, build_apk, lua_code, user_id)
        
        with open(apk_file_path, "rb") as f:
            await message.reply_document(
                document=f,
                filename="Moya_Igra.apk",
                caption="📱 **Ваша игра упакована в APK!**\n"
                        "Нажмите на файл на телефоне и выберите «Установить».\n\n"
                        "🎉 Приятной игры!",
                reply_markup=PERMANENT_KEYBOARD
            )
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"APK error: {e}")
        await status_msg.edit_text(f"❌ Ошибка сборки APK: {str(e)}", reply_markup=PERMANENT_KEYBOARD)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in user_projects:
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": "gemini-2.5-flash"}

    if data == "build_apk_now":
        await process_apk_build(query.message, user_id)
        return

    if data == "new_game":
        user_projects[user_id]["html"] = ""
        user_projects[user_id]["lua"] = ""
        user_projects[user_id]["awaiting_fix"] = False
        await query.message.reply_text("✨ Выберите игру из списка:", reply_markup=get_preset_inline_keyboard())
        return

    if data == "improve_game":
        user_projects[user_id]["awaiting_fix"] = True
        await query.message.reply_text(
            "✏️ **Что вы хотите изменить в игре?**\nНапишите в сообщении (например: *«сделай 3D машинку быстрее»* или *«добавь ночное освещение»*):",
            reply_markup=PERMANENT_KEYBOARD
        )
        return

    if data.startswith("set_model_"):
        new_model = data.replace("set_model_", "")
        user_projects[user_id]["model"] = new_model
        model_name = AVAILABLE_MODELS.get(new_model, new_model)
        await query.message.edit_text(
            f"✅ **Модель ИИ изменена на:**\n`{model_name}`",
            reply_markup=get_models_inline_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    presets = {
        "preset_3d_racing": "Полноценная 3D игра Гонки на Three.js: трехмерная бесконечная трасса, 3D машинка с видом сзади, уворачивайся от препятствий, тач-кнопки руля влево-вправо на экране телефона",
        "preset_3d_space": "Полноценная 3D игра Космический полет на Three.js: лети сквозь 3D астероиды в космосе, собирай светящиеся сферы энергии, вид от 3 лица",
        "preset_cat_clicker": "Красочная 2D игра кликер: нажимай на котика, получай монетки, покупай улучшения и увеличивай доход в секунду",
        "preset_match3": "2D игра три в ряд с яркими разноцветными сладостями, счетчиком очков и ходов",
        "preset_snake": "Классическая 2D змейка с большими удобными кнопками управления на экране под телефон"
    }

    if data == "custom_game":
        user_projects[user_id]["awaiting_fix"] = False
        await query.message.reply_text(
            "✍️ **Напишите любую вашу идею (2D или 3D):**\n(Например: *«Хочу 3D лабиринт от первого лица»* или *«Хочу 2D тетрис»*)",
            reply_markup=PERMANENT_KEYBOARD
        )
        return

    if data in presets:
        prompt = presets[data]
        await process_game_creation(query.message, user_id, prompt, is_update=False)

async def process_game_creation(message, user_id: int, prompt: str, is_update: bool):
    selected_model = user_projects.get(user_id, {}).get("model", "gemini-2.5-flash")
    stage_title = "Улучшение игры" if is_update else "Создание 2D/3D игры"
    
    status_msg = await message.reply_text(
        f"⚡ **[{stage_title}]**\n"
        f"🤖 Модель: `{selected_model}`\n"
        f"⏳ Разрабатываю графику и логику... (0 сек)"
    )

    start_time = time.time()
    is_done = False

    async def update_status_timer():
        dots = [".", "..", "...", "...."]
        i = 0
        while not is_done:
            await asyncio.sleep(2)
            if is_done:
                break
            elapsed = int(time.time() - start_time)
            dot = dots[i % len(dots)]
            i += 1
            try:
                await status_msg.edit_text(
                    f"⚡ **[{stage_title}]**\n🤖 Модель: `{selected_model}`\n⏳ ИИ создает мир и механику{dot} ({elapsed} сек)\n🟢 Бот на связи в облаке!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    timer_task = asyncio.create_task(update_status_timer())

    try:
        loop = asyncio.get_event_loop()
        html_code, lua_code = await loop.run_in_executor(None, generate_or_update_game, user_id, prompt, is_update)

        is_done = True
        timer_task.cancel()
        total_sec = int(time.time() - start_time)

        if html_code:
            html_bytes = html_code.encode("utf-8")
            await message.reply_document(
                document=html_bytes,
                filename="game.html",
                caption=f"🎮 **Игра готова за {total_sec} сек!**\n\n"
                        f"👉 **Шаг 1:** Откройте `game.html` в телефоне, чтобы сразу поиграть и оценить 2D/3D графику.\n\n"
                        f"👉 **Шаг 2:** Если игра понравилась — нажмите кнопку **«📱 Собрать в APK»** ниже!",
                reply_markup=get_game_actions_keyboard()
            )

        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        is_done = True
        timer_task.cancel()
        logger.error(f"Ошибка: {e}")
        try:
            await status_msg.edit_text(f"❌ Ошибка генерации: {str(e)}", reply_markup=PERMANENT_KEYBOARD)
        except Exception:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id not in user_projects:
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": "gemini-2.5-flash"}

    if text in ["📱 Собрать игру в APK", "/apk"]:
        await process_apk_build(update.message, user_id)
        return

    if text in ["🤖 Выбрать модель ИИ", "/models"]:
        curr = user_projects[user_id].get("model", "gemini-2.5-flash")
        await update.message.reply_text(
            f"🤖 **Выберите модель Gemini AI:**\nСейчас активна: `{AVAILABLE_MODELS.get(curr, curr)}`",
            reply_markup=get_models_inline_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if text == "🎮 Выбрать готовую игру":
        await update.message.reply_text("Выберите игру из списка:", reply_markup=get_preset_inline_keyboard())
        return

    if text == "🆕 Новая игра":
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": user_projects[user_id].get("model", "gemini-2.5-flash")}
        await update.message.reply_text(
            "✨ **Начинаем новую игру!** Выберите готовую или напишите свою 2D/3D идею:",
            reply_markup=get_preset_inline_keyboard()
        )
        return

    if text == "✏️ Улучшить / Изменить":
        user_projects[user_id]["awaiting_fix"] = True
        await update.message.reply_text(
            "✏️ **Что вы хотите изменить в игре?**\nНапишите в сообщении (например: *«добавь туман»*, *«сделай 3D машинку быстрее»* или *«добавь кнопку паузы»*):",
            reply_markup=PERMANENT_KEYBOARD
        )
        return

    if text == "❓ Помощь":
        curr_m = user_projects[user_id].get("model", "gemini-2.5-flash")
        help_text = (
            "❓ **Как пользоваться:**\n\n"
            "• Создает как **2D игры**, так и полноценные **3D игры** (Three.js/WebGL).\n"
            "• Напишите любую идею (например: *«Сделай 3D полет сквозь кольца»*).\n"
            "• Откройте `game.html` для теста, а когда всё понравится — нажмите **«📱 Собрать игру в APK»**!"
        )
        await update.message.reply_text(help_text, reply_markup=PERMANENT_KEYBOARD, parse_mode="Markdown")
        return

    user_data = user_projects.get(user_id, {})
    is_awaiting_fix = user_data.get("awaiting_fix", False)
    has_existing_code = bool(user_data.get("lua") or user_data.get("html"))
    
    is_update = is_awaiting_fix or has_existing_code
    
    await process_game_creation(update.message, user_id, text, is_update=is_update)

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    threading.Thread(target=self_ping_loop, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("apk", lambda u, c: process_apk_build(u.message, u.effective_user.id)))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"🤖 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
