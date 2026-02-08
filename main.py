import os
import random
import datetime as dt
from datetime import time
from zoneinfo import ZoneInfo

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")


OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

COMPLIMENTS = [
    "Ты сегодня особенно сияешь ✨",
    "Твоя улыбка — мой любимый антистресс 🙂",
    "Ты умная и очень красивая. Комбо!",
    "Мне нравится, как ты выглядишь.",
    "С тобой любая мелочь становится приятнее 💛",
    "Ты самая сладкая",
    "Твои сиси ваууу :))"
]

UNIVERSE_ANSWERS = [
    "Да.",
    "Нет.",
    "Скорее да.",
    "Скорее нет.",
    "Определенно да.",
    "Определенно нет.",
    "Спроси позже.",
    "Сейчас не время.",
    "Ты и так знаешь ответ 🙂",
    "Рискни — и выиграешь.",
    "Лучше подожди немного.",
    "Это приведет к хорошему.",
    "Будь аккуратнее с этим.",
    "Доверься интуиции.",
]

JOB_NAME = "hourly_compliment"
WEATHER_JOB_NAME = "daily_varna_weather_0700"

BTN_COMPLIMENT = "get_compliment"
BTN_UNIVERSE = "ask_universe"
BTN_WEATHER = "get_weather"

WAITING_QUESTION_KEY = "waiting_universe_question"

VARNA_TZ = ZoneInfo("Europe/Sofia")  # Варна/Болгария


def pick_compliment() -> str:
    return random.choice(COMPLIMENTS)


def pick_universe_answer() -> str:
    return random.choice(UNIVERSE_ANSWERS)


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💌 Получить комплимент",
                              callback_data=BTN_COMPLIMENT)],
        [InlineKeyboardButton("🔮 Ответ от вселенной",
                              callback_data=BTN_UNIVERSE)],
        [InlineKeyboardButton("🌤 Погода / как одеться",
                              callback_data=BTN_WEATHER)],
    ])


async def get_weather_varna() -> dict:
    """
    Возвращает dict с temp, feels_like, desc, wind, rain (bool)
    """
    if not OPENWEATHER_API_KEY:
        return {"error": "NO_API_KEY"}

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": "Varna,BG",
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    temp = float(data["main"]["temp"])
    feels_like = float(data["main"]["feels_like"])
    desc = data["weather"][0]["description"]
    wind = float(data.get("wind", {}).get("speed", 0.0))
    rain = bool(data.get("rain"))  # если есть rain в ответе — вероятен дождь

    return {
        "temp": temp,
        "feels_like": feels_like,
        "desc": desc,
        "wind": wind,
        "rain": rain,
    }


def outfit_advice(temp: float, wind: float, rain: bool) -> str:
    tips = []

    # базово по температуре
    if temp >= 27:
        tips.append("Очень тепло: лёгкое платье/шорты, футболка 👗🩳")
    elif 20 <= temp < 27:
        tips.append("Тепло: футболка + лёгкая кофта на вечер 👕")
    elif 12 <= temp < 20:
        tips.append("Прохладно: кофта/худи или лёгкая куртка 🧥")
    elif 5 <= temp < 12:
        tips.append("Холодно: куртка + что-то тёплое снизу 🧣")
    else:
        tips.append("Очень холодно: тёплая куртка, шарф/шапка ❄️🧤")

    # ветер
    if wind >= 8:
        tips.append("Ветрено — лучше закрытая куртка/капюшон 🌬")

    # дождь
    if rain:
        tips.append("Возьми зонт/капюшон ☔️")

    return " ".join(tips)


async def build_weather_message() -> str:
    w = await get_weather_varna()
    if w.get("error") == "NO_API_KEY":
        return (
            "🌤 Хочу подсказать по погоде в Варне, но нет ключа OpenWeather.\n"
            "Сделай так:\n"
            "1) возьми API key на OpenWeather\n"
            "2) в терминале: export OPENWEATHER_API_KEY=\"...\"\n"
            "3) перезапусти бота"
        )

    temp = w["temp"]
    feels = w["feels_like"]
    desc = w["desc"]
    wind = w["wind"]
    rain = w["rain"]

    advice = outfit_advice(temp, wind, rain)

    return (
        "🌤 Погода в Варне сейчас:\n"
        f"• {temp:.0f}°C (ощущается как {feels:.0f}°C)\n"
        f"• {desc}\n"
        f"• ветер {wind:.0f} м/с\n\n"
        f"👗 Как одеться: {advice}"
    )


async def send_weather_now(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await build_weather_message()
    await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=main_keyboard())


async def send_weather_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.data["chat_id"]
    # await send_weather_now(chat_id, context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    context.bot_data["target_chat_id"] = chat_id
    context.user_data[WAITING_QUESTION_KEY] = False

    # 1) ставим/обновляем комплименты каждый час
    for job in context.job_queue.get_jobs_by_name(JOB_NAME):
        job.schedule_removal()

    context.job_queue.run_repeating(
        callback=send_compliment_job,
        interval=60 * 60,
        first=5,
        name=JOB_NAME,
        data={"chat_id": chat_id},
    )

    # 2) ставим/обновляем погоду каждый день в 07:00 по Варне
    for job in context.job_queue.get_jobs_by_name(WEATHER_JOB_NAME):
        job.schedule_removal()

    context.job_queue.run_daily(
        callback=send_weather_job,
        time=time(7, 0, tzinfo=VARNA_TZ),
        name=WEATHER_JOB_NAME,
        data={"chat_id": chat_id},
    )

    await update.message.reply_text(
        "Привет! 💌\n"
        "— Комплименты: каждый час\n"
        "— Погода в Варне + как одеться: каждый день в 07:00\n\n"
        "И можно кнопками: комплимент / вселенная / погода.",
        reply_markup=main_keyboard(),
    )

    # 3) по старту сразу отправляем погоду+совет
    await send_weather_now(chat_id, context)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for job in context.job_queue.get_jobs_by_name(JOB_NAME):
        job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(WEATHER_JOB_NAME):
        job.schedule_removal()

    context.user_data[WAITING_QUESTION_KEY] = False

    await update.message.reply_text(
        "Ок, остановил таймеры. Если снова надо — /start",
        reply_markup=main_keyboard(),
    )


async def next_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.bot_data.get(
        "target_chat_id") or update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=pick_compliment(),
        reply_markup=main_keyboard(),
    )


async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[WAITING_QUESTION_KEY] = True
    await update.message.reply_text(
        "🔮 Напиши свой вопрос одним сообщением — и я отвечу от вселенной.",
        reply_markup=main_keyboard(),
    )


async def send_compliment_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.data["chat_id"]

    now = dt.datetime.now()
    if 0 <= now.hour < 9:
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=pick_compliment(),
        reply_markup=main_keyboard(),
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == BTN_COMPLIMENT:
        context.user_data[WAITING_QUESTION_KEY] = False
        await query.message.reply_text(pick_compliment(), reply_markup=main_keyboard())
        return

    if query.data == BTN_UNIVERSE:
        context.user_data[WAITING_QUESTION_KEY] = True
        await query.message.reply_text(
            "🔮 Напиши вопрос (например: «Стоит ли мне …?») — отвечу.",
            reply_markup=main_keyboard(),
        )
        return

    if query.data == BTN_WEATHER:
        context.user_data[WAITING_QUESTION_KEY] = False
        await query.message.reply_text(await build_weather_message(), reply_markup=main_keyboard())
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get(WAITING_QUESTION_KEY, False):
        return

    question = (update.message.text or "").strip()
    if not question:
        return

    context.user_data[WAITING_QUESTION_KEY] = False

    await update.message.reply_text(
        f"🔮 Вопрос: {question}\n"
        f"Ответ: {pick_universe_answer()}",
        reply_markup=main_keyboard(),
    )


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            'Нет токена. Задай переменную окружения: export BOT_TOKEN="..."')

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("next", next_now))
    app.add_handler(CommandHandler("ask", ask_cmd))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
