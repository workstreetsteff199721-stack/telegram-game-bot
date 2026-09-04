import logging
import json
import os
import io
import time
import asyncio
import zipfile
import subprocess
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

TELEGRAM_TOKEN = "8994105870:AAGdJsv0GkpZfXUnOAf9YQ5UUphVvZFzBOs"
GEMINI_KEY = "AIzaSyC2D7Ou-4LhCeuJnzsCbsvCbPlV1AI0bQQ"

BASE_DIR = r"C:\Users\A__D__M__I__N\Desktop\TelegramGameBot"
JAVA_BIN = r"C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot\bin\java.exe"
JAR_SIGNER = os.path.join(BASE_DIR, "uber-apk-signer.jar")
BASE_APK = os.path.join(BASE_DIR, "love_embed.apk")

AVAILABLE_MODELS = {
    "gemini-3.8-flash": "⚡ Gemini 3.8 Flash (Самая новая и умная)",
    "gemini-3.7-flash": "🚀 Gemini 3.7 Flash (Очень быстрая)",
    "gemini-3.5-flash": "💡 Gemini 3.5 Flash (Стабильная)",
    "gemini-2.5-flash": "⚙️ Gemini 2.5 Flash (Классическая)"
}

user_projects = {}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

PERMANENT_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🎮 Выбрать готовую игру"), KeyboardButton("🆕 Новая игра")],
        [KeyboardButton("🤖 Выбрать модель ИИ"), KeyboardButton("✏️ Улучшить / Изменить")],
        [KeyboardButton("❓ Помощь")]
    ],
    resize_keyboard=True
)

SYSTEM_PROMPT = """
Ты — профессиональный разработчик мобильных игр.
Ты умеешь создавать игры с нуля и ДОРАБАТЫВАТЬ существующие игры по запросу пользователя.

Всегда выдавай ПОЛНЫЙ рабочий обновленный код СРАЗУ В ДВУХ ВАРИАНТАХ:
1) Lua-код для Android APK (движок Love2D)
2) HTML5-код для быстрого теста в браузере (HTML, Canvas, CSS, JS в одном файле)

ФОРМАТ ОТВЕТА (СТРОГО СОБЛЮДАЙ):
```lua
-- здесь полный код Love2D (main.lua)
```
```html
<!-- здесь полный код HTML5 -->
```

ОБЩИЕ ТРЕБОВАНИЯ:
- Адаптация под сенсорный экран смартфона (крупные элементы, тач-события или клики).
- Красивая яркая графика, счетчик очков (Score), кнопка перезапуска.
- Все рисуется кодом без внешних картинок (фигуры, текст, Canvas).
"""

def generate_or_update_game(user_id: int, user_prompt: str, is_update: bool = False) -> tuple:
    user_data = user_projects.get(user_id, {})
    current_lua = user_data.get("lua", "")
    current_html = user_data.get("html", "")
    selected_model = user_data.get("model", "gemini-3.8-flash")
    
    if is_update and (current_lua or current_html):
        prompt_context = (
            f"{SYSTEM_PROMPT}\n\n"
            f"ТЕКУЩИЙ КОД ИГРЫ (LUA):\n```lua\n{current_lua}\n```\n\n"
            f"ТЕКУЩИЙ КОД ИГРЫ (HTML):\n```html\n{current_html}\n```\n\n"
            f"ЗАПРОС НА ДОРАБОТКУ:\n{user_prompt}\n\n"
            f"Внеси запрошенные изменения и выдай ПОЛНЫЙ исправленный код игры в блоках ```lua ... ``` и ```html ... ```."
        )
    else:
        prompt_context = f"{SYSTEM_PROMPT}\n\nПользователь создает НОВУЮ игру:\n{user_prompt}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={GEMINI_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt_context}]}
        ]
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=90)
    if response.status_code != 200:
        url_fallback = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
        response = requests.post(url_fallback, headers=headers, json=payload, timeout=90)
        if response.status_code != 200:
            raise Exception(f"Ошибка Gemini API: {response.status_code} {response.text}")
    
    data = response.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise Exception("Не удалось распарсить ответ Gemini")

    new_lua = ""
    new_html = ""

    if "```lua" in text:
        new_lua = text.split("```lua")[1].split("```")[0].strip()
    
    if "```html" in text:
        new_html = text.split("```html")[1].split("```")[0].strip()

    if new_lua or new_html:
        user_projects[user_id]["lua"] = new_lua if new_lua else current_lua
        user_projects[user_id]["html"] = new_html if new_html else current_html
        user_projects[user_id]["awaiting_fix"] = False

    return user_projects[user_id]["lua"], user_projects[user_id]["html"]

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

    cmd = [JAVA_BIN, '-jar', JAR_SIGNER, '-a', out_apk_path, '--overwrite', '--allowResign']
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        logger.error(f"Sign error: {p.stderr}")
        raise Exception("Не удалось подписать APK-файл")
        
    return out_apk_path

def get_preset_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("🐱 Кликер с котиком", callback_data="preset_cat_clicker")],
        [InlineKeyboardButton("🍬 Три в ряд (Конфетки)", callback_data="preset_match3")],
        [InlineKeyboardButton("🐍 Веселая Змейка", callback_data="preset_snake")],
        [InlineKeyboardButton("🏎 Гонки на машинках", callback_data="preset_racing")],
        [InlineKeyboardButton("✨ Написать свою идею текстом", callback_data="custom_game")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_models_inline_keyboard(user_id: int):
    current_model = user_projects.get(user_id, {}).get("model", "gemini-3.8-flash")
    keyboard = []
    for model_id, name in AVAILABLE_MODELS.items():
        prefix = "✅ " if model_id == current_model else "⚪ "
        keyboard.append([InlineKeyboardButton(f"{prefix}{name}", callback_data=f"set_model_{model_id}")])
    return InlineKeyboardMarkup(keyboard)

async def post_init(application: Application):
    bot_commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("models", "Выбрать модель ИИ"),
        BotCommand("menu", "Список готовых игр"),
        BotCommand("new", "Создать новую игру"),
        BotCommand("fix", "Улучшить текущую игру"),
        BotCommand("help", "Помощь")
    ]
    await application.bot.set_my_commands(bot_commands)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_projects:
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": "gemini-3.8-flash"}
    
    text = (
        "👋 **Здравствуйте! Я помогу вам создать игру для телефона.**\n\n"
        "🧠 Модель ИИ: **Gemini 3.8 Flash**\n"
        "👇 Выберите готовую игру или используйте кнопки внизу:"
    )
    await update.message.reply_text(text, reply_markup=PERMANENT_KEYBOARD, parse_mode="Markdown")
    await update.message.reply_text("Выберите игру из списка:", reply_markup=get_preset_inline_keyboard())

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in user_projects:
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": "gemini-3.8-flash"}

    if data.startswith("set_model_"):
        new_model = data.replace("set_model_", "")
        user_projects[user_id]["model"] = new_model
        model_name = AVAILABLE_MODELS.get(new_model, new_model)
        await query.message.edit_text(
            f"✅ **Модель ИИ изменена на:**\n`{model_name}`\n\nВсе новые игры будут делаться на этой модели!",
            reply_markup=get_models_inline_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    presets = {
        "preset_cat_clicker": "Красочная игра кликер: нажимай на котика, получай монетки, покупай улучшения и увеличивай доход в секунду",
        "preset_match3": "Игра три в ряд с яркими разноцветными сладостями, счетчиком очков и ходов",
        "preset_snake": "Классическая змейка с большими удобными кнопками управления на экране под телефон",
        "preset_racing": "Гонки на машинках: уворачивайся от встречных машин, собирай канистры с бензином"
    }

    if data == "custom_game":
        user_projects[user_id]["awaiting_fix"] = False
        await query.message.reply_text(
            "✍️ **Напишите любую вашу идею:**\n(Например: *«Хочу пасьянс»* или *«Хочу арканоид»*)",
            reply_markup=PERMANENT_KEYBOARD
        )
        return

    if data in presets:
        prompt = presets[data]
        await process_game_creation(query.message, user_id, prompt, is_update=False)

async def process_game_creation(message, user_id: int, prompt: str, is_update: bool):
    selected_model = user_projects.get(user_id, {}).get("model", "gemini-3.8-flash")
    stage_title = "Улучшение игры" if is_update else "Создание игры"
    
    status_msg = await message.reply_text(
        f"⚙️ **[{stage_title}]**\n"
        f"🤖 Модель: `{selected_model}`\n"
        f"⏳ Статус: Пишу код игры... (0 сек)\n"
        f"🟢 Бот работает, не завис!"
    )

    start_time = time.time()
    is_done = False

    # Фоновая задача обновления таймера в реальном времени
    async def update_status_timer():
        elapsed = 0
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
                if elapsed < 20:
                    status_text = f"⚙️ **[{stage_title}]**\n🤖 Модель: `{selected_model}`\n⏳ Статус: ИИ придумывает правила и пишет код{dot} ({elapsed} сек)\n🟢 Бот работает, подождите немного..."
                elif elapsed < 40:
                    status_text = f"⚙️ **[{stage_title}]**\n🤖 Модель: `{selected_model}`\n⏳ Статус: Компилирую логику и собираю графику{dot} ({elapsed} сек)\n🟢 Почти готово, обрабатываю код..."
                else:
                    status_text = f"⚙️ **[{stage_title}]**\n🤖 Модель: `{selected_model}`\n⏳ Статус: Финальная обработка и упаковка{dot} ({elapsed} сек)\n🟢 Все отлично, завершаю генерацию..."
                
                await status_msg.edit_text(status_text, parse_mode="Markdown")
            except Exception:
                pass

    timer_task = asyncio.create_task(update_status_timer())

    try:
        # 1. Генерируем код
        loop = asyncio.get_event_loop()
        lua_code, html_code = await loop.run_in_executor(None, generate_or_update_game, user_id, prompt, is_update)

        # 2. Упаковываем в APK
        apk_file_path = None
        if lua_code:
            try:
                await status_msg.edit_text(
                    f"📱 **[Компиляция APK]**\n"
                    f"⏱ Время разработки: {int(time.time() - start_time)} сек\n"
                    f"📦 Упаковываю и подписываю файл приложения..."
                )
            except Exception: pass
            apk_file_path = await loop.run_in_executor(None, build_apk, lua_code, user_id)

        is_done = True
        timer_task.cancel()

        total_sec = int(time.time() - start_time)

        # 3. Отправляем готовые файлы
        if html_code:
            html_bytes = html_code.encode("utf-8")
            await message.reply_document(
                document=html_bytes,
                filename="game.html",
                caption=f"🌐 **1. Проверить в браузере (`game.html`)**\n⏱ Время сборки: {total_sec} сек"
            )

        if apk_file_path:
            with open(apk_file_path, "rb") as f:
                await message.reply_document(
                    document=f,
                    filename="Moya_Igra.apk",
                    caption=f"📲 **2. Установить на телефон (`Moya_Igra.apk`)**\n"
                            f"⚡ Готово за {total_sec} сек!\n\n"
                            f"👇 Для изменений нажмите кнопку **«✏️ Улучшить / Изменить»** внизу!",
                    reply_markup=PERMANENT_KEYBOARD
                )

        # 4. ВАЖНО: Удаляем временное статусное сообщение, чтобы чат был чистым!
        try:
            await status_msg.delete()
        except Exception:
            pass

    except Exception as e:
        is_done = True
        timer_task.cancel()
        logger.error(f"Ошибка: {e}")
        try:
            await status_msg.edit_text(
                f"❌ **Произошла ошибка при сборке:**\n`{str(e)}`\n\nПопробуйте еще раз или выберите модель Gemini 3.7 Flash!",
                reply_markup=PERMANENT_KEYBOARD,
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_id not in user_projects:
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": "gemini-3.8-flash"}

    if text in ["🤖 Выбрать модель ИИ", "/models"]:
        curr = user_projects[user_id].get("model", "gemini-3.8-flash")
        await update.message.reply_text(
            f"🤖 **Выберите модель Gemini AI:**\nСейчас активирована: `{AVAILABLE_MODELS.get(curr, curr)}`",
            reply_markup=get_models_inline_keyboard(user_id),
            parse_mode="Markdown"
        )
        return

    if text == "🎮 Выбрать готовую игру":
        await update.message.reply_text("Выберите игру из списка:", reply_markup=get_preset_inline_keyboard())
        return

    if text == "🆕 Новая игра":
        user_projects[user_id] = {"lua": "", "html": "", "awaiting_fix": False, "model": user_projects[user_id].get("model", "gemini-3.8-flash")}
        await update.message.reply_text(
            "✨ **Начинаем новую игру!** Выберите готовую или напишите свою идею:",
            reply_markup=get_preset_inline_keyboard()
        )
        return

    if text == "✏️ Улучшить / Изменить":
        user_projects[user_id]["awaiting_fix"] = True
        await update.message.reply_text(
            "✏️ **Что вы хотите изменить в игре?**\nНапишите в сообщении (например: *«сделай скорость меньше»*, *«кнопки крупнее»* или *«поменяй цвет»*):",
            reply_markup=PERMANENT_KEYBOARD
        )
        return

    if text == "❓ Помощь":
        curr_m = user_projects[user_id].get("model", "gemini-3.8-flash")
        help_text = (
            "❓ **Как пользоваться:**\n\n"
            f"• Модель ИИ: **{AVAILABLE_MODELS.get(curr_m, curr_m)}**\n"
            "• Нажмите **«🎮 Выбрать готовую игру»** или напишите свою идею.\n"
            "• Скачайте `game.html` (попробовать сразу) или `Moya_Igra.apk` (установить на телефон).\n"
            "• Нажмите **«✏️ Улучшить / Изменить»**, чтобы добавить новые функции!"
        )
        await update.message.reply_text(help_text, reply_markup=PERMANENT_KEYBOARD, parse_mode="Markdown")
        return

    user_data = user_projects.get(user_id, {})
    is_awaiting_fix = user_data.get("awaiting_fix", False)
    has_existing_code = bool(user_data.get("lua") or user_data.get("html"))
    
    is_update = is_awaiting_fix or has_existing_code
    
    await process_game_creation(update.message, user_id, text, is_update=is_update)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Бот с живым таймером и авто-удалением временных сообщений запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
