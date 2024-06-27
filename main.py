import asyncio
import subprocess
import re

import requests
import telebot
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from telebot import types
import logging
from g4f.client import Client
import g4f
from config import TOKEN, PRICE, information_about_company
import os
import sqlite3
from gtts import gTTS
import pytube
import speech_recognition as sr
import datetime
import schedule
import time
from googletrans import Translator
from urllib import parse, request
import hashlib

translator = Translator()
# https://www.youtube.com/watch?v=1aA1WGON49E&ab_channel=TEDxTalks

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

os.environ["PATH"] += os.pathsep + r"C:\ffmpeg\bin"

g4f_client = Client()

INTRODUCTION_MESSAGE = ("¡Hola! Я — Tiabaldo, твой виртуальный преподаватель испанского языка. Soy Tiabaldo, tu profesor virtual de español.")

FREE_PERIOD = 3 * 60  # 10 seconds for testing

ADMIN_USER_ID = 1262676599

bot = telebot.TeleBot(TOKEN)

merchant_login = "tiabaldo_bot"
pass1 = "testh777"
pass2 = "testh777"

robokassa_payment_url = 'https://auth.robokassa.ru/Merchant/Index.aspx'

# Function to calculate MD5 signature
def calculate_signature(*args) -> str:
    joined_string = ':'.join(str(arg) for arg in args)
    return hashlib.md5(joined_string.encode()).hexdigest()

# Function to create a payment link
def generate_payment_link(cost: float, order_id: str, description: str, is_test: int = 1) -> str:
    signature = calculate_signature(merchant_login, cost, order_id, pass1)
    data = {
        'MerchantLogin': merchant_login,
        'OutSum': cost,
        'InvId': order_id,
        'Description': description,
        'SignatureValue': signature,
        'IsTest': is_test
    }
    return f'{robokassa_payment_url}?{parse.urlencode(data)}'

def escape_markdown_v2(text):
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([{}])'.format(re.escape(escape_chars)), r'\\\1', text)


def init_db():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute(
            '''CREATE TABLE IF NOT EXISTS used_free_period (user_id INTEGER PRIMARY KEY)''')
        c.execute(
            '''CREATE TABLE IF NOT EXISTS premium_users (user_id INTEGER PRIMARY KEY, expiration_date TEXT)''')
        c.execute(
            '''CREATE TABLE IF NOT EXISTS payments (user_id INTEGER, payment_id TEXT, PRIMARY KEY (user_id, payment_id))''')
        conn.commit()
    finally:
        conn.close()


def has_used_free_period(user_id):
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute(
            'SELECT user_id FROM used_free_period WHERE user_id = ?', (user_id,))
        result = c.fetchone()
    finally:
        conn.close()
    return result is not None


def mark_free_period_used(user_id):
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute(
            'INSERT OR IGNORE INTO used_free_period (user_id) VALUES (?)', (user_id,))
        conn.commit()
    finally:
        conn.close()


def is_premium_user(user_id):
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute(
            'SELECT expiration_date FROM premium_users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        if result:
            expiration_date = datetime.datetime.strptime(
                result[0], '%Y-%m-%d %H:%M:%S')
            return expiration_date > datetime.datetime.now()
        else:
            return False
    finally:
        conn.close()


def mark_as_premium(user_id):
    # Placeholder: Implement logic to mark user as premium in your system
    expiration_date = datetime.datetime.now() + datetime.timedelta(days=30)  # Premium subscription for 30 days
    expiration_date_str = expiration_date.strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO premium_users (user_id, expiration_date) VALUES (?, ?)',
                  (user_id, expiration_date_str))
        conn.commit()
    finally:
        conn.close()


def remind_about_subscription():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('SELECT user_id FROM premium_users WHERE expiration_date < ? AND expiration_date > ?',
                  (datetime.datetime.now() + datetime.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'),
                  datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        users_to_remind = c.fetchall()
        for user_id in users_to_remind:
            bot.send_message(
                user_id, "You have 2 days left until the end of your subscription.")
    finally:
        conn.close()


# Schedule the reminder to run daily
schedule.every().day.at("09:00").do(remind_about_subscription)


def clear_used_free_periods():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('DELETE FROM used_free_period')
        conn.commit()
    finally:
        conn.close()


def clear_expired_premium_subscriptions():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('DELETE FROM premium_users WHERE expiration_date < ?',
                  (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()
    finally:
        conn.close()


def clear_premium_periods():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('DELETE FROM premium_users')
        conn.commit()
    finally:
        conn.close()


init_db()

user_start_times = {}


def daily_job():
    clear_expired_premium_subscriptions()
    print("Expired premium subscriptions cleared.")


schedule.every().day.at("00:00").do(daily_job)


async def generate_response(text):
    print("Generating response...")
    response = await g4f.ChatCompletion.create_async(
        model=g4f.models.default,
        messages=[{"role": "user", "content": text}],
        provider=g4f.Provider.FreeGpt
    )
    print("Response generated.")
    return response


def voice_to_text(voice_file, language="es-ES"):
    print("Converting voice to text...")
    recognizer = sr.Recognizer()
    with sr.AudioFile(voice_file) as source:
        audio_data = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio_data, language=language)
        print("Text converted from voice:", text)
        return text
    except sr.UnknownValueError:
        print("Google Speech Recognition could not understand audio")
        return None
    except sr.RequestError:
        print("Could not request results from Google Speech Recognition service")
        return None


def convert_to_wav(audio_file):
    print("Converting audio file to WAV format...")
    wav_file = 'converted_audio.wav'
    subprocess.run(['ffmpeg', '-y', '-i', audio_file, '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', wav_file])
    print("Audio file converted to WAV format.")
    return wav_file



def text_to_speech(text, language="es"):
    print("Converting text to speech...")
    tts = gTTS(text=text, lang=language)
    ogg_file = 'response.ogg'
    tts.save(ogg_file)
    print("Text converted to speech and saved as OGG format.")
    return ogg_file



@bot.message_handler(commands=['start', 'language'])
def start(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=1)

    # Adding language selection options
    markup.add(types.KeyboardButton("🇪🇸 Español"), types.KeyboardButton("🇷🇺 Русский"))

    bot.reply_to(message, "Hola! 🌟 Elige tu idioma preferido / Выберите ваш язык", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text in ["🇪🇸 Español", "🇷🇺 Русский"])
def select_language(message):
    language = message.text

    if language == "🇪🇸 Español":
        # Set user language to Spanish
        markup = types.ReplyKeyboardMarkup(row_width=1)
        markup.add(types.KeyboardButton("🚀 Inicio"),types.KeyboardButton("🅰 Transcripción"),
                   types.KeyboardButton('👥 Perfil'),
                   types.KeyboardButton("❓ ¿Qué es eso?"))
        welcome_message = "¡Hola! Soy Tiabaldo, tu profesor virtual de español\n" \
"⠀⠀⠀\n" \
"¡7 pasos para automatizar el idioma español!\n \n" \
"✅ De 20 a 30 veces más barato que los tutores.\n" \
"✅ Práctica nueva cada día. ORAL Y AUDITIVA.\n" \
"Lo que más atención requiere de los estudiantes.\n" \
"¡Habla y pregunta al bot todo lo que quieras mediante un mensaje de voz, te responderá de la misma manera!\n" \
"Si eres principiante, puedes activar la transcripción y la traducción por un tiempo.\n" \
"✅ Corrección de errores incluso en la versión gratis.\n" \
"✅ Puedes hablar con él, practicar temas léxicos/gramaticales específicos, discutir un artículo, conocer el significado de una palabra (presiona start)\n" \
"✅ Transcripción de audio y videos de YouTube (Premium)\n" \
"✅ Activar GPT-4 (Premium)\n" \
"✅ Más minutos de conversación en (Premium)\n \n" \
"⠀⠀⠀\n" \
"¡Haz clic en el menú y vamos!\n" \
"La suscripción Premium se encuentra en la sección <perfil> 499 rublos/mes.\n"

    elif language == "🇷🇺 Русский":
        # Set user language to Russian
        markup = types.ReplyKeyboardMarkup(row_width=1)
        markup.add(types.KeyboardButton("🚀 Начать"),
                   types.KeyboardButton("🅰 Транскрибация"),
                   types.KeyboardButton("📟Перевод"),
                   types.KeyboardButton('👥 Профиль'),
                   types.KeyboardButton("❓ Что это?"))
        welcome_message = "¡Hola! Я — Tiabaldo, твой виртуальный преподаватель испанского языка.\n" \
"⠀⠀⠀\n" \
    "7 шагов к автоматизации испанского языка!\n" \
"✅ В 20-30 раз дешевле репетиторов.\n" \
"✅ Каждый день новая практика. УСТНАЯ И АУДИРОВАНИЕ.\n" \
"То, что требует больше всего внимания у изучающих.\n" \
"Расскажите и спросите бота всё, что угодно голосовым сообщением, он ответит вам также!\n" \
"Если вы начинающий, можно включить транскрипцию и перевод на какое-то время.\n" \
"✅ Исправление ошибок даже в бесплатном тарифе.\n" \
"✅ Можно с ним поговорить, попрактиковать конкретные лексические/грамматические темы, обсудить статью, узнать значение слова (нажимай start) \n" \
"✅ Транскрипция аудио и роликов youtube (Premium)\n" \
"✅ Включить GPT-4o (Premium)\n" \
"✅ Больше минут разговора в (Premium)\n" \
"⠀⠀⠀\n" \
"Жми меню и поехали!\n" \
"Premium-подписка находится в разделе <профиль>.\n" \
"499 руб/месяц.\n" \

    bot.send_message(message.chat.id, welcome_message, reply_markup=markup)


translation_enabled = False


# Define a dictionary to store the announcement messages
announcement_messages = {}

# Handler for the /announce command
@bot.message_handler(commands=['announce'])
def start_announcement(message):
    # Set the user's state to 'waiting_for_announcement'
    user_id = message.from_user.id
    announcement_messages[user_id] = ''
    bot.send_message(user_id, "Отправьте оповещение, чтобы всем разослать.")

# Handler for receiving the announcement message
@bot.message_handler(func=lambda message: message.from_user.id in announcement_messages and announcement_messages[message.from_user.id] == '' and notification_preferences.get(message.from_user.id, True))
def receive_announcement(message):
    user_id = message.from_user.id
    announcement_message = message.text
    # Save the announcement message
    announcement_messages[user_id] = announcement_message
    bot.send_message(user_id, "Сообщение для оповещения сохранено. Начинаю отправку...")

    # Proceed with the announcement process
    send_announcement_to_all(user_id)

def send_announcement_to_all(user_id):
    # Fetch all users
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('SELECT user_id FROM used_free_period')
        users = c.fetchall()
    finally:
        conn.close()

    # Send the announcement to users who have notifications enabled
    for user in users:
        if notification_preferences.get(user[0], True):
            bot.send_message(user[0], announcement_messages[user_id])

    # Inform the admin about the successful announcement
    bot.send_message(user_id, "Сообщение успешно отправлено всем пользователям.")



@bot.message_handler(func=lambda message: message.text == "🅰 Transcripción")
def toggle_transcription(message):
    global translation_enabled

    translation_enabled = not translation_enabled

    if translation_enabled:
        bot.reply_to(message, "La transcripción está activada. Los mensajes de voz se transcribirán.")
    else:
        bot.reply_to(message, "La transcripción está desactivada.")

@bot.message_handler(func=lambda message: message.text == "🅰 Транскрибация")
def toggle_transcription(message):
    global translation_enabled

    translation_enabled = not translation_enabled

    if translation_enabled:
        bot.reply_to(message, "Транскрибация включена. Голосовые сообщения будут транскрибироваться.")
    else:
        bot.reply_to(message, "Транскрибация выключена.")

# Handler for the "Translation" button
@bot.message_handler(func=lambda message: message.text == "📟Перевод")
def toggle_translation(message):
    global translation_enabled
    translation_enabled = not translation_enabled
    if translation_enabled:
        bot.send_message(message.chat.id, "Перевод включен. Все испанские сообщения будут переведены на русский.")
    else:
        bot.send_message(message.chat.id, "Перевод выключен.")


@bot.message_handler(func=lambda message: message.text == '🚀 Inicio')
def start_button(message):
    markup_start = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup_start.add(types.KeyboardButton('solo charlar'), types.KeyboardButton("palabra"),
                     types.KeyboardButton('practicar temas'), types.KeyboardButton("la transcripción"),
                     types.KeyboardButton("parafrasear"), types.KeyboardButton('artículo de actualidad'),
                     types.KeyboardButton("aprender español"), types.KeyboardButton('🔙 Volver al menú principal'))
    bot.reply_to(message, "Hola, soy tu profesor de español. Pregúntame lo que quieras.", reply_markup=markup_start)


@bot.message_handler(func=lambda message: message.text == '📝 Audio a texto')
def handle_transcribe_button(message):
    user_id = message.from_user.id
    if not is_premium_user(user_id):
        bot.reply_to(message, "Esta función sólo está disponible para usuarios Premium.")
    else:
        msg = bot.reply_to(message, "Proporcione la URL de YouTube para la transcripción:")
        bot.register_next_step_handler(msg, transcribe_youtube_video)


@bot.message_handler(func=lambda message: message.text == '❓ Что это?')
def who_are_we(message):
    markup_who = types.ReplyKeyboardMarkup(row_width=1)
    markup_who.add(types.KeyboardButton('👫 Познакомиться'), types.KeyboardButton("📚 Материалы"),
                   types.KeyboardButton("🎓 Обучение"), types.KeyboardButton('📒 Консультации'),
                   types.KeyboardButton("💡 Идеи к улучшению"), types.KeyboardButton("💃 Мероприятия на испанском"),
                   types.KeyboardButton('🔙 Назад в главное меню'))
    bot.reply_to(message, information_about_company, reply_markup=markup_who)


@bot.message_handler(func=lambda message: message.text == '🎓 Обучение')
def start_button(message):
    bot.reply_to(message, "🇪🇸🎓 Обучение проходит в группах, индивидуально, через тееграм с наставником и самостоятельно на образовательной платформе.\n" \
"⠀⠀⠀\n" \
"Абонемент Básico участника нашего сообщества включает:\n" \
"⠀⠀⠀\n" \
"✅ Качественное обучение: в группе (8 занятий в месяц), мини-группе или индивидуально.\n" \
"✅ Бесплатный разговорный клуб для продолжающих в вс.\n" \
"✅ Множество МАТЕРИАЛОВ во время обучения (распечатки, фишечки по обучению, эффективные методики, аудио-видео сборники).\n" \
"✅ ПОДПИСКУ на обучающую ОНЛАЙН ПЛАТФОРМУ APRENDEMICA в подарок: теория, практика и материалы, идущие параллельно программе, полезно для пропустивших и тех, кто хочет больше.\n" \
"✅ Доступ к БИБЛИОТЕКЕ книг, видео и аудио в живую и онлайн.\n" \
"✅ А также подписку по желанию на технологию изучения языка.\n" \
"✅ СООБЩЕСТВО любителей, профессионалов и носителей испанского языка. Оплачиваемые и/или бесплатные МЕРОПРИЯТИЯ для практики 🤗\n" \
"✅ Поддержка каждым из преподавателей по вопросам, связанным с языком, обучением, мероприятиями, культурой, путешествиями, обучением за границей, с огромным удовольствием поделимся опытом и знаниями с единомышленниками.\n" \
"⠀⠀⠀\n" \
"Подробнее: aprendemica.com")


@bot.message_handler(func=lambda message: message.text == '📚 Материалы')
def start_button(message):
    bot.reply_to(message, "¡Hola! Adoramos la creatividad y clases vivas\n" \
"Мы обожаем креативность и живые уроки ❤️\n" \
"С октября 2007 года мы создаем материалы с любовью, чтобы изучение и взаимодействие с самым красивым языком мира были интересными и эффективными. \n" \
"⠀⠀⠀\n" \
"📒 У нас есть как печатные материалы на озон (https://www.ozon.ru/seller/akademiya-ispanskogo-yazyka-545110/products/?miniapp=seller_545110), например, для подарка:\n" \
"🔸 Рабочая тетрадь по Испанскому языку GRAMÁTICA MÁGICA\n" \
"🔸 Планер на испанском (https://t.me/estrella_moretti/13)\n" \
"🔸 Карточки «110 самых употребимых глаголов испанского языка»\n" \
"🔸 Брелоки испанской тематики\n" \
"...\n" \
"⠀⠀⠀\n" \
"P.D.: Если нет в наличии на озоне, а вам надо срочно, напишите, возможно, на складе ещё не выставили, а у нас есть.\n" \
"⠀⠀⠀\n" \
"📒 И цифровые материалы (https://boosty.to/estrellamoretti) на платформе и в клубе испанистов (https://t.me/estrella_moretti/21) для уроков испанского и разговорных клубов.\n" \
"⠀⠀⠀\n" \
"Каждый раз выходит разбор и задания к новой статье, видео, жаркие вопросы к обсуждению! 😍 Можно подписаться на месячный абонемент или приобрести понравившийся материал отдельно.\n" \
"⠀⠀⠀\n" \
"🔸 Материал про детективные фильмы\n" \
"🔸 Материал на фильмы и сериалы\n" \
"🔸 Подборка видео про рождество\n" \
"🔸 Inteligencia emocional y frases tóxicas\n" \
"🔸 Цели\n" \
"🔸 Креативность\n" \
"⠀⠀⠀\n" \
"✔️ Испанский по песням https://t.me/estrella_moretti/18")


@bot.message_handler(func=lambda message: message.text == '💃 Мероприятия на испанском')
def start_button(message):
    bot.reply_to(message, "Разговорные клубы: Каждое воскресенье в Краснодаре проходит клуб разговорного испанского языка. Это бесплатное мероприятие открыто для всех любителей испанского, включая носителей языка и энтузиастов.\n" \
"⠀⠀⠀\n" \
"Киноклуб: Мы организуем кино-вечера, где показываем фильмы на испанском языке. Эти сеансы включают обсуждения фильмов для улучшения аудирования и беглости речи.\n" \
"⠀⠀⠀\n" \
"Кулинарные мастер-классы: Примите участие в наших кулинарных мастер-классах и научитесь готовить традиционные блюда Испании и Латинской Америки, одновременно практикуя испанский.\n" \
"⠀⠀⠀\n" \
"Учебные поездки: Мы предлагаем учебные поездки в Испанию и страны Латинской Америки. Эти поездки позволяют студентам погружаться в культуру и практиковать язык в реальных условиях.\n" \
"⠀⠀⠀\n" \
"Клубы настольных игр: Присоединяйтесь к нашим сессиям настольных игр на испанском языке, это веселый и динамичный способ практиковать язык в расслабленной обстановке.\n" \
"⠀⠀⠀\n" \
"Культурные мероприятия: Описание: Мы организуем различные культурные мероприятия, такие как фестивали, презентации и концерты, где празднуется культура испаноязычных стран.\n" \
"⠀⠀⠀\n" \
"➡ Все мероприятия на испанском языке\n" \
"https://t.me/aprendemica")


@bot.message_handler(func=lambda message: message.text == '📒 Консультации')
def start_button(message):
    bot.reply_to(message, "Консультации преподавателям и студентам:\n" \
"Помощь в составлении уроков, создании материалов, решении ситуаций.\n" \
"Студентам помощь в организации эффективного обучения, подбор хороших материалов и источников.\n" \
"⠀⠀⠀\n" \
"Подробнее: aprendemica.com")


@bot.message_handler(func=lambda message: message.text == '👫 Познакомиться')
def start_button(message):
    bot.reply_to(message, "Добро пожаловать в Мир испанского языка Aprendemica 🇪🇸🎓. Мы - центр испаноязычной культуры, где Испания и Латинская Америка встречаются, чтобы предложить вам полноценный опыт изучения испанского языка а нашей Академии 🌍. Мы предлагаем полные курсы всех уровней 📚, сообщество таких же увлеченных людей: разговорные клубы 💬, культурные мастер-классы 🎨, кино-вечера 🎥, путешествия ✈️ и многое другое.\n" \
"⠀⠀⠀\n" \
"Наша цель - не только обучить вас языку, но жить им 🌟. Каждое занятие, будь то в группе 👥, индивидуально 🧑‍🏫 или онлайн 💻, на 70% сосредоточено на разговорной практике 🗣️. Преподаватели будут направлять вас, чтобы вы эффективно усваивали и применяли язык в реальных ситуациях. Мы предоставляем доступ к обширной библиотеке учебных материалов 📖, включая книги, видео и аудио, как в физическом, так и в онлайн-формате. Кроме того, наши студенты имеют доступ в подарок к нашей образовательной онлайн-платформе APRENDEMICA 📲, включающей теорию, практику и дополнительные материалы 📑.\n" \
"⠀⠀⠀\n" \
"✅ Практики и расписание мероприятий:\n" \
"https://t.me/aprendemica\n" \
"✅ Советы и трюки изучения языков:\n" \
"https://goo.gl/jnejS1\n" \
"✅ Материалы электронные и печатные издания \n" \
"https://aprendemica.online\n" \
"✔ Поездки, методика, истории\n" \
"https://instagram.com/club_espanol\n" \
"✔ Наша группа вк, студенты, преподаватели, кино-клубы, кулинарные, разговорные клубы, йога на испанском.\n" \
"https://vk.com/la_escuela\n" \
"❤ Результаты обучения уже через 1-3 месяца:\n" \
"https://vk.cc/cqjrkX  \n" \
"❤ Отзывы и результаты: \n" \
"https://vk.com/topic-39169507_36969197 ")


@bot.message_handler(func=lambda message: message.text == '💡 Идеи к улучшению')
def prompt_for_idea(message):
    # Create a keyboard with a "Cancel" button
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Отмена'))

    msg = bot.reply_to(message,
                       "Пожалуйста, напишите свою идею по улучшению нашего сервиса или нажмите «Отмена», чтобы вернуться назад:",
                       reply_markup=markup)
    bot.register_next_step_handler(msg, handle_idea_or_cancel)


##############################################################################################################################################################

@bot.message_handler(func=lambda message: message.text == '❓ ¿Qué es eso?')
def who_are_we(message):
    markup_who = types.ReplyKeyboardMarkup(row_width=1)
    markup_who.add(types.KeyboardButton('👫 Quienes somos'), types.KeyboardButton("📚 Materiales"),
                   types.KeyboardButton("🎓 Aprender idiomas"), types.KeyboardButton('📒 Consultas'),
                   types.KeyboardButton("💡 Ideas para mejorar"), types.KeyboardButton("💃 Eventos en español"),
                   types.KeyboardButton('🔙 Volver al menú principal'))
    bot.reply_to(message, information_about_company, reply_markup=markup_who)


@bot.message_handler(func=lambda message: message.text == '🎓 Aprender idiomas')
def start_button(message):
    bot.reply_to(message, "🇪🇸🎓 La formación se realiza en grupos, individualmente, a través de Telegram con un mentor y de forma autónoma en la plataforma educativa.\n" \
"⠀⠀⠀\n" \
"El abono Básico para miembros de nuestra comunidad incluye:\n" \
"⠀⠀⠀\n" \
"✅ Educación de calidad: en grupo (8 clases al mes), mini-grupo o individualmente.\n" \
"✅ Club de conversación gratuito para avanzados los domingos.\n" \
"✅ Una gran cantidad de MATERIALES durante el estudio (impresos, trucos de enseñanza, metodologías efectivas, colecciones de audio y video).\n" \
"✅ SUSCRIPCIÓN de regalo a la PLATAFORMA ONLINE EDUCATIVA APRENDEMICA: teoría, práctica y materiales que van en paralelo al programa, útil para los que se pierden clases y para aquellos que quieren más.\n" \
"✅ Acceso a la BIBLIOTECA de libros, videos y audio en vivo y online.\n" \
"✅ Así como la suscripción opcional a la tecnología de aprendizaje de idiomas.\n" \
"✅ COMUNIDAD de aficionados, profesionales y hablantes nativos de español. EVENTOS pagados y/o gratuitos para la práctica 🤗\n" \
"✅ Apoyo de cada uno de los profesores en temas relacionados con el idioma, la enseñanza, eventos, cultura, viajes, estudios en el extranjero, compartiremos con gusto nuestra experiencia y conocimientos con personas afines.\n" \
"⠀⠀⠀\n" \
"Más información: aprendemica.com")


@bot.message_handler(func=lambda message: message.text == '📒 Consultas')
def start_button(message):
    bot.reply_to(message, "Consultas para profesores y estudiantes:\n" \
"Ayuda en la planificación de lecciones, creación de materiales, resolución de situaciones.\n" \
"A los estudiantes, ayuda en la organización de un aprendizaje efectivo, selección de buenos materiales y fuentes.\n" \
"⠀⠀⠀\n" \
"Más información: aprendemica.com")


@bot.message_handler(func=lambda message: message.text == '👫 Quienes somos')
def start_button(message):
    bot.reply_to(message, "Bienvenido al Mundo de Español Aprendemica 🇪🇸🎓. Somos un centro de cultura hispanohablante, donde España y América Latina se encuentran para ofrecerte una experiencia completa de aprendizaje del español en nuestra academia 🌍. Ofrecemos cursos completos de todos los niveles 📚, comunidad de personas igualmente apasionadas: clubes de conversación 💬, talleres culturales 🎨, noches de cine 🎥, viajes ✈️ y mucho más.\n" \
"⠀⠀⠀\n" \
"Nuestro objetivo no es solo enseñarte el idioma, sino también vivirlo 🌟. Cada clase, ya sea en grupo 👥, individual 🧑‍🏫 o en línea 💻, se enfoca en un 70% en la práctica oral 🗣️. Los profesores te guiarán para que adquieras y apliques el idioma de manera efectiva en situaciones reales. Ofrecemos acceso a una biblioteca extensa de materiales didácticos 📖, incluyendo libros, videos y audios, tanto en formato físico como en línea. Además, nuestros estudiantes tienen acceso gratuito a nuestra plataforma educativa en línea APRENDEMICA 📲, que incluye teoría, práctica y materiales adicionales 📑.\n" \
"⠀⠀⠀\n" \
"✅ Prácticas y calendario de eventos:\n" \
"https://t.me/aprendemica\n" \
"✅ Consejos y trucos para el aprendizaje de idiomas:\n" \
"https://goo.gl/jnejS1\n" \
"✅ Materiales electrónicos y publicaciones impresas\n" \
"https://aprendemica.online\n" \
"✔ Viajes, metodología, historias\n" \
"https://instagram.com/club_espanol\n" \
"✔ Nuestro grupo en VK, estudiantes, profesores, clubes de cine, clubes culinarios, clubes de conversación, yoga en español.\n" \
"https://vk.com/la_escuela\n" \
"❤ Resultados de aprendizaje en solo 1-3 meses:\n" \
"https://vk.cc/cqjrkX  \n" \
"❤ Opiniones y resultados: \n" \
"https://vk.com/topic-39169507_36969197 ")


@bot.message_handler(func=lambda message: message.text == '📚 Materiales')
def start_button(message):
    bot.reply_to(message, "¡Hola! Adoramos la creatividad y clases vivas\n" \
"Мы обожаем креативность и живые уроки ❤️\n" \
"С октября 2007 года мы создаем материалы с любовью, чтобы изучение и взаимодействие с самым красивым языком мира были интересными и эффективными. \n" \
"⠀⠀⠀\n" \
"📒 У нас есть как печатные материалы на озон (https://www.ozon.ru/seller/akademiya-ispanskogo-yazyka-545110/products/?miniapp=seller_545110), например, для подарка:\n" \
"🔸 Рабочая тетрадь по Испанскому языку GRAMÁTICA MÁGICA\n" \
"🔸 Планер на испанском (https://t.me/estrella_moretti/13)\n" \
"🔸 Карточки «110 самых употребимых глаголов испанского языка»\n" \
"🔸 Брелоки испанской тематики\n" \
"...\n" \
"⠀⠀⠀\n" \
"P.D.: Если нет в наличии на озоне, а вам надо срочно, напишите, возможно, на складе ещё не выставили, а у нас есть.\n" \
"⠀⠀⠀\n" \
"📒 И цифровые материалы (https://boosty.to/estrellamoretti) на платформе и в клубе испанистов (https://t.me/estrella_moretti/21) для уроков испанского и разговорных клубов.\n" \
"⠀⠀⠀\n" \
"Каждый раз выходит разбор и задания к новой статье, видео, жаркие вопросы к обсуждению! 😍 Можно подписаться на месячный абонемент или приобрести понравившийся материал отдельно.\n" \
"⠀⠀⠀\n" \
"🔸 Материал про детективные фильмы\n" \
"🔸 Материал на фильмы и сериалы\n" \
"🔸 Подборка видео про рождество\n" \
"🔸 Inteligencia emocional y frases tóxicas\n" \
"🔸 Цели\n" \
"🔸 Креативность\n" \
"⠀⠀⠀\n" \
"✔️ Испанский по песням https://t.me/estrella_moretti/18")


@bot.message_handler(func=lambda message: message.text == '💃 Eventos en español')
def start_button(message):
    bot.reply_to(message, "Clubs de Conversación: Cada domingo en Krasnodar, se celebra un club de conversación en español. Este evento es gratuito y abierto a todos los amantes del idioma español, incluidos hablantes nativos y aficionados.\n" \
"⠀⠀⠀\n" \
"Cineclub: Organizamos noches de cine donde se proyectan películas en español. Estas sesiones incluyen discusiones sobre las películas para mejorar la comprensión auditiva y la fluidez en el idioma.\n" \
"⠀⠀⠀\n" \
"Talleres Culinarios: Participa en nuestros talleres de cocina y aprende a preparar platos típicos de España y América Latina mientras practicas el español.\n" \
"⠀⠀⠀\n" \
"Viajes Educativos: Ofrecemos viajes educativos a España y países de América Latina. Estos viajes permiten a los estudiantes sumergirse en la cultura y practicar el idioma en un entorno real.\n" \
"⠀⠀⠀\n" \
"Juegos de Mesa y Clubes de Juegos: Únete a nuestras sesiones de juegos de mesa en español, una forma divertida y dinámica de practicar el idioma en un ambiente relajado.\n" \
"⠀⠀⠀\n" \
"Eventos Culturales: Organizamos diversos eventos culturales, como festivales, presentaciones y conciertos, donde se celebra la cultura hispanohablante.\n" \
"⠀⠀⠀\n" \
"➡ Todos los eventos en español:\n" \
"https://t.me/aprendemica")


@bot.message_handler(func=lambda message: message.text == '💡 Ideas para mejorar')
def prompt_for_idea(message):
    # Create a keyboard with a "Cancel" button
    markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Cancelar'))

    msg = bot.reply_to(message,
                       "Escriba su idea para mejorar nuestro servicio o haga clic en «Cancelar» para volver atrás:",
                       reply_markup=markup)
    bot.register_next_step_handler(msg, handle_idea_or_cancel)


def handle_idea_or_cancel(message):
    if message.text.lower() == 'Cancelar':
        bot.send_message(message.chat.id, "Su solicitud se ha cancelado correctamente.")
        start(message)
    else:
        forward_idea_to_admin(message)


########################################################################################################################################################

def forward_idea_to_admin(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    user_idea = message.text

    # Format the user info
    user_info = f"User ID: {user_id}\n"
    if username:
        user_info += f"Username: @{username}\n"
    if first_name or last_name:
        user_info += f"Name: {first_name} {last_name}\n"

    # Format the message to include user info and their idea
    admin_message = f"Была подана идея по улучшению сервиса:\n\n{user_idea}\n\nОт:\n{user_info}"

    # Send the idea to the admin
    bot.send_message(ADMIN_USER_ID, admin_message)

    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"),
               types.KeyboardButton('👥 Профиль'), types.KeyboardButton("📟Перевод"),
               types.KeyboardButton("🅰 Транскрибация"),
               types.KeyboardButton("❓ Что это?"))

    # Confirm receipt to the user
    bot.reply_to(message, "Спасибо за ваш отзыв! Ваша идея была отправлена в нашу команду.", reply_markup = markup)


@bot.message_handler(func=lambda message: message.text == '🚀 Начать')
def start_button(message):
    markup_start = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup_start.add(types.KeyboardButton('Поболтать'), types.KeyboardButton("Про слово"),
                     types.KeyboardButton('Практиковать темы'), types.KeyboardButton("Транскрипция"),
                     types.KeyboardButton("Перефразировать"), types.KeyboardButton('Про актуальную статью'),
                     types.KeyboardButton("Учить классически"), types.KeyboardButton('🔙 Назад в главное меню'))
    bot.reply_to(message, "Привет, я ваш учитель испанского. Спросите меня о чем угодно.", reply_markup=markup_start)


# New handler for the 'Transcribe' feature
@bot.message_handler(func=lambda message: message.text == '📝 Аудио в текст')
def handle_transcribe_button(message):
    user_id = message.from_user.id
    if not is_premium_user(user_id):
        bot.reply_to(message, "Эта функция доступна только для премиум-пользователей.")
    else:
        msg = bot.reply_to(message, "Пожалуйста, укажите URL-адрес YouTube для транскрипции:")
        bot.register_next_step_handler(msg, transcribe_youtube_video)


def transcribe_youtube_video(message):
    user_id = message.from_user.id
    youtube_url = message.text

    try:
        # Step 1: Download YouTube video
        bot.reply_to(message, "Загрузка видео...")
        yt = pytube.YouTube(youtube_url)
        video = yt.streams.filter(only_audio=True).first()
        video_file = video.download(filename="youtube_audio.mp4")

        # Step 2: Extract audio from video using ffmpeg
        bot.reply_to(message, "Извлечение звука из видео...")
        audio_file = "youtube_audio.wav"
        subprocess.run(
            ['ffmpeg', '-i', video_file, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', audio_file])

        # Step 3: Convert audio to text
        bot.reply_to(message, "Транскрибирование аудио...")
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_file) as source:
            audio_data = recognizer.record(source)
            # Specify the language for recognition (Spanish in this case)
            text = recognizer.recognize_google(audio_data, language="es-ES")

        # Step 4: Send the transcription back to the user
        bot.reply_to(message, f"Транскрипция:\n\n{text}")

        # Cleanup: Remove downloaded and processed files
        os.remove(video_file)
        os.remove(audio_file)

    except Exception as e:
        bot.reply_to(message, f"An error occurred: {e}")


#####################################################################################################################################################
# Profile button handler
@bot.message_handler(func=lambda message: message.text == '👥 Perfil')
def handle_profile_button(message):
    user_id = message.from_user.id
    markup_profile = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup_profile.add(types.KeyboardButton('⛳Activar GPT-4o'), types.KeyboardButton('📝 Audio a texto'),types.KeyboardButton("🌎 Idioma"),
                       types.KeyboardButton('🔄 Reinicie'), types.KeyboardButton("💎Premium"),
                       types.KeyboardButton('🔙 Volver al menú principal'))
    if is_premium_user(user_id):
        bot.reply_to(message, "Su situación: Premium", reply_markup=markup_profile)
    else:
        bot.reply_to(message, "Su situación: Free", reply_markup=markup_profile)


@bot.message_handler(func=lambda message: message.text == '🔄 Reinicie')
def handle_transcribe_button(message):
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Inicio"), types.KeyboardButton("🅰 Transcripción"),
               types.KeyboardButton('👥 Perfil'),
               types.KeyboardButton("❓ ¿Qué es eso?"))
    time.sleep(3)
    bot.reply_to(message, 'El reinicio se ha realizado correctamente ♻️', reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == '💎Premium')
def handle_transcribe_button(message):
    user_id = message.from_user.id
    if is_premium_user(user_id):
        bot.reply_to(message, "Ya tiene premium, ¡enhorabuena!")
    else:
        msg = bot.reply_to(message, "Premium es muy útil: \n ✅ Transcricpión de los videos de youtube (Premium)\n ✅ Activar GPT-4o (Premium)\n ✅ Más conversación (Premium)\n" )
        bot.reply_to(message, msg)


@bot.message_handler(func=lambda message: message.text == '⛳Activar GPT-4o')
def handle_transcribe_button(message):
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Inicio"), types.KeyboardButton("🅰 Transcripción"),
               types.KeyboardButton('👥 Perfil'),
               types.KeyboardButton("❓ ¿Qué es eso?"))
    user_id = message.from_user.id
    if not is_premium_user(user_id):
        bot.reply_to(message, "Esta función sólo está disponible para usuarios Premium.", reply_markup=markup)
    else:
        msg = bot.reply_to(message, "Activar GPT-4o\nMás rápido y fiable")


@bot.message_handler(func=lambda message: message.text == '🔙 Volver al menú principal')
def back_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Inicio"), types.KeyboardButton('📝 Audio a texto'),
               types.KeyboardButton('👥 Perfil'),
               types.KeyboardButton("❓ ¿Qué es eso?"))
    bot.reply_to(message, "Hola, soy tu profesor de español. Pregúntame lo que quieras.", reply_markup=markup)


#######################################################################################################################################

notification_preferences = {}


@bot.message_handler(func=lambda message: message.text == '👥 Профиль')
def handle_profile_button(message):
    user_id = message.from_user.id
    markup_profile = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup_profile.add(types.KeyboardButton('⛳Включить GPT-4o'), types.KeyboardButton('📝 Аудио в текст'),
                       types.KeyboardButton("🌎 Язык"), types.KeyboardButton('🔔 Оповещения'),
                       types.KeyboardButton('🔄 Перезапуск'), types.KeyboardButton("💎Premium."),
                       types.KeyboardButton('🔙 Назад в главное меню'))
    if is_premium_user(user_id):
        bot.send_message(user_id, """
    ¡Hola, amigo! 🇪🇸

    🧑‍💻 <b>Ваш тариф:</b> premium
    ⏳ <b>Ваш баланс:</b> осталось 3 мин / 10,000 токенов GPT-3.5 
    🛠 <b>Ваш режим:</b> GPT-3.5
    🔔 <b>Оповещения:</b> включено
    🌐 <b>Язык:</b> системный язык

    🆓 <b>Бесплатный тариф</b> включает 3 минуты устного общения в день, либо 10000 токенов.

    💎 <b>Premium тариф</b> включает:
    ✅ 15 минут устного общения каждый день
    ✅ 30 тысяч токенов GPT-3.5 каждый день
    ✅ 800 GPT-4o и возможность работать с (документами, изображениями, сайтами), транскрибацией.

    При переходе на премиум-версию с вас будет взиматься ежемесячная оплата 499 рублей, либо 7 usd, пока вы не отключите эту опцию. Возврат не предусмотрен. Оплатить можно по QR-коду, карте.
    """, parse_mode="HTML", reply_markup=markup_profile)
    else:
        bot.send_message(user_id, """
    ¡Hola, amigo! 🇪🇸

    🧑‍💻 <b>Ваш тариф:</b> бесплатный
    ⏳ <b>Ваш баланс:</b> осталось 3 мин / 10,000 токенов GPT-3.5 
    🛠 <b>Ваш режим:</b> GPT-3.5
    🔔 <b>Оповещения:</b> включено (материалы для практики, новые функции)
    🌐 <b>Язык:</b> системный язык

    🆓 <b>Бесплатный тариф</b> включает 3 минуты устного общения в день, либо 10000 токенов.

    💎 <b>Premium тариф</b> включает:
    ✅ 15 минут устного общения каждый день
    ✅ 30 тысяч токенов GPT-3.5 каждый день
    ✅ 800 GPT-4o и возможность работать с (документами, изображениями, сайтами), транскрибацией.

    При переходе на премиум-версию с вас будет взиматься ежемесячная оплата 499 рублей, либо 7 usd, пока вы не отключите эту опцию. Возврат не предусмотрен. Оплатить можно по QR-коду, карте.
    """, parse_mode="HTML", reply_markup=markup_profile)



@bot.message_handler(func=lambda message: message.text == '🔔 Оповещения')
def handle_notification_button(message):
    user_id = message.from_user.id
    markup_notification = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    markup_notification.add(types.KeyboardButton('Включить'), types.KeyboardButton('Выключить'))

    bot.reply_to(message, "Выберите действие:", reply_markup=markup_notification)

# Handler for enabling or disabling notifications
@bot.message_handler(func=lambda message: message.text in ['Включить', 'Выключить'])
def handle_notification_preference(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"),
               types.KeyboardButton('👥 Профиль'), types.KeyboardButton("📟Перевод"),
               types.KeyboardButton("🅰 Транскрибация"),
               types.KeyboardButton("❓ Что это?"))
    if message.text == 'Включить':
        notification_preferences[user_id] = True
        bot.reply_to(message, "Оповещения включены.", reply_markup = markup)
    else:
        notification_preferences[user_id] = False
        bot.reply_to(message, "Оповещения выключены.", reply_markup = markup)




@bot.message_handler(func=lambda message: message.text in ['🌎 Язык', '🌎 Idioma'])
def yazik_func(message):
    markup_language = types.ReplyKeyboardMarkup(row_width=1)
    markup_language.add(types.KeyboardButton("🇪🇸 Español"), types.KeyboardButton("🇷🇺 Русский"))
    bot.send_message(message.chat.id, "Elige tu idioma preferido / Выберите ваш язык",
                     reply_markup=markup_language)


@bot.message_handler(func=lambda message: message.text == '🔄 Перезапуск')
def handle_transcribe_button(message):
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"), types.KeyboardButton('📝 Аудио в текст'),
               types.KeyboardButton('👥 Профиль'), types.KeyboardButton("📟Перевод"),
               types.KeyboardButton("❓ Что это?"))
    time.sleep(3)
    bot.reply_to(message, 'Перезапуск был успешен ♻️',reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == '🔙 Назад в главное меню')
def back_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"), types.KeyboardButton('📝 Аудио в текст'),
               types.KeyboardButton('👥 Профиль'), types.KeyboardButton("📟Перевод"),
               types.KeyboardButton("❓ Что это?"))
    bot.reply_to(message, "Привет! Я твой учитель испанского языка. Спросите меня о чем угодно", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == '💎Premium.')
def handle_transcribe_button(message):
    user_id = message.from_user.id

    # Create inline keyboard markup for payment options
    markup_buy = types.InlineKeyboardMarkup()
    yoomoney_button = types.InlineKeyboardButton(text="Robokassa", callback_data='pay_robokassa')
    crypto_button = types.InlineKeyboardButton(text="Crypto", callback_data='pay_crypto')
    markup_buy.add(yoomoney_button, crypto_button)

    # Send a message prompting the user to choose a payment method
    bot.send_message(
        message.chat.id,  # Correct attribute is 'chat.id' instead of 'chat_id'
        "Вы пользуетесь нашим сервисом в течение 1 минуты. Чтобы продолжить пользоваться сервисом, вам необходимо произвести оплату. Пожалуйста, выберите способ оплаты:",
        reply_markup=markup_buy
    )

    # Create reply keyboard markup for main options
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(
        types.KeyboardButton("🚀 Начать"),
        types.KeyboardButton('📝 Аудио в текст'),
        types.KeyboardButton('👥 Профиль'),
        types.KeyboardButton("📟Перевод"),
        types.KeyboardButton("❓ Что это?")
    )

    # Check if the user is a premium user and respond accordingly
    if is_premium_user(user_id):  # Ensure the function 'is_premium_user' is defined
        bot.reply_to(message, "Вы уже имеете премиум, поздравляем!", reply_markup=markup)
    else:
        bot.reply_to(message, "Премиум даёт полезные функции:\n ✅ Транскрипция аудио и роликов youtube (Premium)\n ✅ Включить GPT-4o (Premium)\n ✅ Больше минут разговора в (Premium)\n", reply_markup=markup_buy)


@bot.message_handler(func=lambda message: message.text == '⛳Включить GPT-4o')
def handle_transcribe_button(message):
    user_id = message.from_user.id
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"), types.KeyboardButton('📝 Аудио в текст'),
               types.KeyboardButton('👥 Профиль'), types.KeyboardButton("📟Перевод"),
               types.KeyboardButton("❓ Что это?"))
    if not is_premium_user(user_id):
        bot.reply_to(message, "Эта функция доступна только для премиум-пользователей.", reply_markup=markup)
    else:
        bot.reply_to(message, "Активировать GPT-4o\nБолее быстрый и надёжный")
        markup_profile = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
        markup_profile.add(types.KeyboardButton('⛳Активировать'), types.KeyboardButton('⛔ Деактивировать'))
        bot.reply_to(message, "Выберите действие:", reply_markup=markup_profile)


@bot.message_handler(func=lambda message: message.text == '⛳Активировать')
def activate_button(message):
    bot.reply_to(message, "Поздравляю, GPT-4o был успешно активирован!")
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"),
               types.KeyboardButton("🅰 Транскрибация"),
               types.KeyboardButton("📟Перевод"),
               types.KeyboardButton('👥 Профиль'),
               types.KeyboardButton("❓ Что это?"))
    bot.reply_to(message, "Выберите действие:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == '⛔ Деактивировать')
def deactivate_button(message):
    bot.reply_to(message, "GPT-4o был успешно деактивирован!")
    # Return to the initial keyboard layout
    markup = types.ReplyKeyboardMarkup(row_width=1)
    markup.add(types.KeyboardButton("🚀 Начать"),
               types.KeyboardButton("🅰 Транскрибация"),
               types.KeyboardButton("📟Перевод"),
               types.KeyboardButton('👥 Профиль'),
               types.KeyboardButton("❓ Что это?"))
    bot.reply_to(message, "Выберите действие:", reply_markup=markup)

# Function to create pending_payments and orders tables if not exists
# Function to create pending_payments and orders tables if not exists
def create_tables():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS pending_payments (
                user_id TEXT PRIMARY KEY,
                product_description TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    finally:
        conn.close()


@bot.message_handler(commands=['buy777'])
def buy_handler(message):
    chat_id = message.chat.id
    # Create inline keyboard with two options: Robokassa and Crypto
    markup = types.InlineKeyboardMarkup()
    robokassa_button = types.InlineKeyboardButton(text="RoboKassa", callback_data='pay_robokassa')
    crypto_button = types.InlineKeyboardButton(text="Crypto", callback_data='pay_crypto')
    markup.add(robokassa_button, crypto_button)

    bot.send_message(chat_id,
                     "Вы пользуетесь нашим сервисом в течение 10 минут. Чтобы продолжить пользоваться сервисом, вам необходимо произвести оплату. Пожалуйста, выберите способ оплаты:",
                     reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_robokassa') or call.data.startswith('check_'))
def handle_payment_option(call):
    chat_id = call.message.chat.id
    if call.data == 'pay_robokassa':
        order_id = str(chat_id)  # Using chat ID as order ID
        product_description = "Payment for Service"  # Example product description
        payment_url = generate_payment_link(950.0, order_id, product_description)

        # Create inline keyboard with Pay and Check Payment options
        markup = types.InlineKeyboardMarkup()
        pay_button = types.InlineKeyboardButton(text="Оплатить", url=payment_url)
        check_button = types.InlineKeyboardButton(text="Проверить", callback_data=f'check_{order_id}')
        markup.add(pay_button, check_button)

        bot.send_message(chat_id, "Пожалуйста, завершите оплату с помощью RoboKassa:", reply_markup=markup)

        # Insert or replace the pending payment into the database
        conn = sqlite3.connect('user_data.db')
        try:
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO pending_payments (user_id, product_description) VALUES (?, ?)',
                      (order_id, product_description))
            c.execute('INSERT OR REPLACE INTO orders (order_id, status) VALUES (?, ?)', (order_id, "pending"))
            conn.commit()
        finally:
            conn.close()
    elif call.data.startswith('check_'):
        order_id = call.data.split('_')[1]
        payment_status = check_payment_status(order_id)
        if payment_status == "Success":
            bot.send_message(chat_id, f'Payment status for order {order_id}: Success')
            update_order_status(order_id, "success")
            mark_as_premium(order_id)
            send_success_message(order_id, "Payment for Service")
        else:
            bot.send_message(chat_id, f'Payment status for order {order_id}: {payment_status}')


# Flask route for handling Robokassa ResultURL
@app.route('/result', methods=['POST'])
def result():
    request_data = request.form
    received_sum = request_data.get('OutSum')
    order_id = request_data.get('InvId')
    signature = request_data.get('SignatureValue')

    if check_signature_result(order_id, received_sum, signature, pass2):
        # Handle successful payment
        update_order_status(order_id, "success")
        product_description = request_data.get('Description')
        # Implement product delivery logic here
        if product_description == "Payment for Service":
            mark_as_premium(order_id)  # Example: Grant premium access
            send_success_message(order_id, product_description)  # Send success message for test payment
        elif product_description == "Another Product":
            # Handle other product/service delivery
            pass
        return 'OK' + order_id
    else:
        update_order_status(order_id, "failed")
        return 'Wrong Try again man..'

def send_success_message(order_id, product_description):
    try:
        if product_description == "Payment for Service":
            # Send specific message for test payment success
            bot.send_message(order_id, "YOUR KEY:RUIBAS&!*482471hd8a")
        else:
            # Handle other product success messages
            pass
    except Exception as e:
        print(f"Error sending message to {order_id}: {str(e)}")

# Function to verify signature from Robokassa
def check_signature_result(order_number: str, received_sum: str, received_signature: str, password: str) -> bool:
    signature = calculate_signature(order_number, received_sum, password)
    return signature.lower() == received_signature.lower()

# Function to check payment status via Robokassa API
def check_payment_status(order_id):
    signature = calculate_signature(merchant_login, order_id, pass1)
    params = {
        'MerchantLogin': merchant_login,
        'InvoiceID': order_id,
        'Signature': signature
    }
    response = requests.get('https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpState', params=params)
    if response.status_code == 200:
        result = response.text
        if result.startswith('OK'):
            return "Success"
        else:
            return "Pending"
    else:
        return "Failed"

def update_order_status(order_id, status):
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('UPDATE orders SET status = ? WHERE order_id = ?', (status, order_id))
        conn.commit()
    finally:
        conn.close()

# Function to check pending payments and update status
def check_pending_payments():
    conn = sqlite3.connect('user_data.db')
    try:
        c = conn.cursor()
        c.execute('SELECT user_id FROM pending_payments')
        pending_payments = c.fetchall()
        for user_id in pending_payments:
            order_id = user_id[0]
            payment_status = check_payment_status(order_id)
            if payment_status == "Success":
                update_order_status(order_id, "success")
                mark_as_premium(order_id)
                send_success_message(order_id, "Payment for Service")  # Send success message for test payment
                c.execute('DELETE FROM pending_payments WHERE user_id = ?', (order_id,))
        conn.commit()
    finally:
        conn.close()

# Set up the scheduler to check pending payments
scheduler = BackgroundScheduler()
scheduler.add_job(check_pending_payments, 'interval', minutes=5)
scheduler.start()

# Flask route for handling success endpoint
@app.route('/success', methods=['GET'])
def success():
    order_id = request.args.get('InvId')
    # Handle success (e.g., show a success message)
    return f'Payment successful for order {order_id}'

# Flask route for handling fail endpoint
@app.route('/fail', methods=['GET'])
def fail():
    order_id = request.args.get('InvId')
    # Handle failure (e.g., show a failure message)
    return f'Payment failed for order {order_id}'

# Telegram bot command to start payment process
@bot.message_handler(commands=['start'])
def handle_start(message):
    markup = telebot.types.InlineKeyboardMarkup()
    pay_button = telebot.types.InlineKeyboardButton(text="PAY", callback_data="pay")
    check_payment_button = telebot.types.InlineKeyboardButton(text="Check Payment", callback_data="check_payment")
    markup.add(pay_button, check_payment_button)
    bot.send_message(message.chat.id, "Choose an action:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    if call.data == "pay":
        order_id = call.message.chat.id
        product_description = "Payment for Service"  # Example product description
        payment_link = generate_payment_link(950.0, order_id, product_description)
        bot.send_message(call.message.chat.id, f'Click the link to pay: {payment_link}')
        conn = sqlite3.connect('user_data.db')
        try:
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO pending_payments (user_id, product_description) VALUES (?, ?)', (order_id, product_description))
            c.execute('INSERT OR REPLACE INTO orders (order_id, status) VALUES (?, ?)', (order_id, "pending"))
            conn.commit()
        finally:
            conn.close()
    elif call.data == "check_payment":
        order_id = call.message.chat.id
        payment_status = check_payment_status(order_id)
        if payment_status == "Success":
            bot.send_message(call.message.chat.id, f'Payment status for order {order_id}: Success')
            update_order_status(order_id, "success")
            mark_as_premium(order_id)
            send_success_message(order_id, "Payment for Service")
        else:
            bot.send_message(call.message.chat.id, f'Payment status for order {order_id}: {payment_status}')





# /saf command handler (clear used free periods)
@bot.message_handler(commands=['saf'])
def handle_saf(message):
    user_id = message.from_user.id
    if user_id == ADMIN_USER_ID:
        clear_used_free_periods()
        clear_premium_periods()
        bot.reply_to(message, "All used free periods have been cleared.")
    else:
        bot.reply_to(message, "You are not authorized to use this command.")


# Callback query handler for checking payment
@bot.callback_query_handler(func=lambda call: call.data.startswith('check'))
def check_handler(callback_query):
    payment_id = callback_query.data.split('_')[1]
    result = check(payment_id)
    if result:
        chat_id = result.get('chat_id')
        mark_as_premium(chat_id)  # Mark the user as a premium user
        bot.send_message(callback_query.message.chat.id, "Oплата прошла успешно! поздравляем с покупкой Premium")
    else:
        bot.send_message(callback_query.message.chat.id, "Оплата ещё не прошла или ошибка")


# Function to check if user is within free period
def is_within_free_period(user_id):
    if user_id not in user_start_times:
        user_start_times[user_id] = time.time()
        return True
    start_time = user_start_times[user_id]
    elapsed_time = time.time() - start_time
    if elapsed_time > FREE_PERIOD:
        mark_free_period_used(user_id)
        return False
    return True


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.from_user.id

    # Check if user is within free period or is a premium user
    if not is_within_free_period(user_id) and not is_premium_user(user_id):
        buy_handler(message.chat.id)  # Pass chat.id directly
        return

    if translation_enabled:
        # If translation mode is enabled
        if message.text:
            # Translate only the generated responses
            user_message = message.text
            user_message_with_reminder = f"Привет ты больше не языковой помощник, теперь учитель испанского языка \n{user_message} отвечай СТРОГО на испанском, говори очень очень коротко "

            print("Generating response for text message...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ai_response = loop.run_until_complete(generate_response(user_message_with_reminder))

            # Translate the generated response
            translation = translator.translate(ai_response, src='es', dest='ru')

            # Send original and translated messages
            bot.send_message(message.chat.id, f"{ai_response}")
            bot.send_message(message.chat.id, f"Перевод:\n\n{translation.text}")
    else:
        # If translation mode is off or message is empty, proceed with generating response
        if message.text:
            print("Text message received:", message.text)
            user_message = message.text
            user_message_with_reminder = f"Привет ты больше не языковой помощник, теперь учитель испанского языка \n{user_message} отвечай СТРОГО на испанском, говори очень очень коротко "

            print("Generating response for text message...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ai_response = loop.run_until_complete(generate_response(user_message_with_reminder))

            bot.reply_to(message, ai_response)


@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    user_id = message.from_user.id
    if not is_within_free_period(user_id) and not is_premium_user(user_id):
        buy_handler(message.chat.id)  # Pass chat.id directly
        return

    print("Voice message received.")
    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    print("Voice file downloaded.")

    with open('voice_message.ogg', 'wb') as new_file:
        new_file.write(downloaded_file)
    print("Voice file saved locally as 'voice_message.ogg'.")

    wav_file = convert_to_wav('voice_message.ogg')
    text = voice_to_text(wav_file, language="es-ES")  # Set the language to Spanish
    if text:
        print("Voice message converted to text:", text)
        user_message_with_reminder = f"Привет ты теперь учитель испанского языка \n{text} отвечай СТРОГО на испанском, большие ответы не нужны"

        print("Generating response for voice message...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ai_response = loop.run_until_complete(generate_response(user_message_with_reminder))

        print("Converting text response to speech...")
        speech_file = text_to_speech(ai_response, language="es")  # Set the TTS language to Spanish

        translation = translator.translate(ai_response, src='es', dest='ru')

        print("Sending voice response...")

        # Check if transcription is enabled
        if translation_enabled:
            # Send both voice and text messages
            bot.send_voice(message.chat.id, open(speech_file, 'rb'))
            escaped_ai_response = escape_markdown_v2(ai_response)
            spoiler_text = f"||{escaped_ai_response}||"
            bot.send_message(message.chat.id, spoiler_text, parse_mode='MarkdownV2')
            bot.send_message(message.chat.id, translation.text)
        else:
            # Send only the voice message
            bot.send_voice(message.chat.id, open(speech_file, 'rb'))

        logging.info("Voice response and text sent.")
    else:
        print("Could not understand the voice message.")
        bot.reply_to(message, "Повторите снова, я вас не расслышал")


# Ensure database and tables are created
create_tables()


logging.basicConfig(level=logging.INFO)

# Start polling
print("Bot is starting...")
bot.polling()

while True:
    schedule.run_pending()
    time.sleep(60)
