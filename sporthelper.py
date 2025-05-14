import datetime
import random
import sqlite3
import threading
import time

import numpy as np
import requests
import schedule as sched
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from telebot import TeleBot, types

TELEGRAM_TOKEN = '8050281814:AAE2kmU7ZJHQwJMCMlJaZL-te3HpHNELSvw'
bot = TeleBot(TELEGRAM_TOKEN)
DATABASE_NAME = "sports.db"
YANDEX_MAPS_API_KEY = "a48685ac-a8e0-4f0b-a36c-e44b74e14362"

user_answers = {}
user_data = {}

questions = [
    "1. Какой у вас уровень физической активности (низкий, средний, высокий)?",
    "2. Какой тип физической нагрузки вы предпочитаете (индивидуальный, командный)?",
    "3. Какую интенсивность тренировок вы предпочитаете (низкая, средняя, высокая)?",
    "4. Сколько времени в неделю вы готовы уделять спорту (0-2 часа, 2-4 часа, 4+ часа)?",
    "5. Что для вас важнее в спорте (улучшение физической формы, общение, соревнование, снятие стресса)?",
    "6. Вам больше нравится заниматься на открытом воздухе или в помещении?",
    "7. Вы предпочитаете спорт, требующий координации и ловкости, или силовой?",
    "8. У вас есть какие-либо ограничения по здоровью или травмы (да/нет)?",
]

activity_factors = {
    "низкий": 1.2,
    "средний": 1.55,
    "высокий": 1.9
}

reminders = [
    "Помни о своей тренировке! Подготовься заранее, чтобы не пропустить ее!",
    "Перерыв в течение дня - отличное время для небольшой активности! Сделай несколько упражнений или прогуляйся!",
    "Не забудь спланировать завтрашний день! Запиши идеи для завтрашней тренировки и спланируй свой рацион.",
    "Время отдохнуть! Помни о своих целях и спланируй свой день заранее!",
    "Твоя тренировка ждет тебя! Пришло время попотеть и приблизиться к своей цели!",
    "Не пропусти свою тренировку! Ты уже на полпути к своей цели!",
    "Ты помнишь, что сегодня нужно тренироваться? Еще не поздно начать!",
    "Запиши свой прием пищи! Следи за своей диетой, чтобы достичь своих целей!",
    "Не забывай о воде! Пей достаточно жидкости, чтобы поддерживать свое тело в форме!",
    "Ты на правильном пути! Твой прогресс впечатляет!",
    "Не сдавайся! Даже маленькие шаги ведут к большим результатам!",
    "Твое тело скажет тебе спасибо!",
    "Помни о своих целях! Они ждут тебя!",
    "Помни, что ты можешь достичь всего, чего захочешь! Просто продолжай двигаться вперед!"
]


def get_surgut_districts():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT district FROM organizations")
    districts = [row[0] for row in cursor.fetchall() if row[0] is not None]
    conn.close()
    return districts


def get_coordinates(address):
    geocode_url = f"https://geocode-maps.yandex.ru/1.x/?apikey={YANDEX_MAPS_API_KEY}&geocode={address}, Сургут&format=json"
    try:
        response = requests.get(geocode_url)
        response.raise_for_status()
        data = response.json()
        coordinates = data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']['Point']['pos']
        longitude, latitude = map(float, coordinates.split())
        return latitude, longitude
    except requests.exceptions.RequestException as e:
        print(f"Error fetching coordinates: {e}")
        return None
    except (KeyError, IndexError, ValueError) as e:
        print(f"Error parsing Yandex Maps response: {e}")
        return None


def get_sports_facilities(district=None, sport_type=None):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    query = "SELECT organization, address, phone FROM organizations"
    conditions = []
    params = []

    if district:
        conditions.append("district=?")
        params.append(district)
    if sport_type and sport_type != "Любой вид спорта":
        conditions.append("sport_type=?")
        params.append(sport_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    facilities = cursor.fetchall()
    conn.close()
    return facilities


def format_facility_info(facility):
    name, address, phone = facility
    coordinates = get_coordinates(address)
    map_link = ""
    if coordinates:
        latitude, longitude = coordinates
        map_link = f"https://yandex.ru/maps/?ll={longitude},{latitude}&z=16&pt={longitude},{latitude}&l=map"
    response_text = f"🏢 {name}\n"
    response_text += f"📍 Адрес: {address}\n"
    response_text += f"📞 Телефон: {phone if phone else 'Не указан'}\n"
    if map_link:
        response_text += f"🗺️ [Показать на карте]({map_link})\n"
    response_text += "\n"
    return response_text


def get_all_chat_ids():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM user_data")
    chat_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return chat_ids


def calculate_calories(gender, weight, height, age, activity_level, goal):
    if gender == "мужской":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    calories = bmr * activity_factors.get(activity_level, 1.2)
    if goal == "похудение":
        calories *= 0.85
    elif goal == "набор массы":
        calories *= 1.15
    protein = weight * 1.8
    fat = calories * 0.25 / 9
    carbs = (calories - protein * 4 - fat * 9) / 4

    return {
        "калории": int(calories),
        "белки": int(protein),
        "жиры": int(fat),
        "углеводы": int(carbs)
    }


X = np.array([
    [2, 1, 2, 2, 0, 0, 0, 1],
    [1, 0, 1, 1, 2, 1, 1, 0],
    [1, 1, 2, 2, 1, 0, 1, 1],
    [0, 0, 0, 1, 0, 1, 0, 0],
    [1, 1, 1, 2, 2, 1, 0, 1],
    [1, 1, 2, 2, 3, 0, 1, 1],
    [1, 1, 2, 2, 3, 1, 0, 1],
    [2, 0, 2, 1, 0, 0, 1, 0],
    [0, 0, 1, 1, 1, 1, 0, 0],
    [1, 1, 1, 2, 1, 0, 0, 1]
])
y = np.array([
    "Бег",
    "Плавание",
    "Велоспорт",
    "Йога",
    "Теннис",
    "Футбол",
    "Баскетбол",
    "Тяжелая атлетика",
    "Пилатес",
    "Волейбол"
])

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = RandomForestClassifier()
model.fit(X_train, y_train)


def predict_sport(feature_vector):
    return model.predict([feature_vector])[0]


def process_answers(answers):
    feature_vector = np.zeros(8)

    if answers[0] == "Низкий":
        feature_vector[0] = 0
    elif answers[0] == "Средний":
        feature_vector[0] = 1
    else:
        feature_vector[0] = 2

    if answers[1] == "Индивидуальный":
        feature_vector[1] = 0
    else:
        feature_vector[1] = 1

    if answers[2] == "Низкая":
        feature_vector[2] = 0
    elif answers[2] == "Средняя":
        feature_vector[2] = 1
    else:
        feature_vector[2] = 2

    if answers[3] == "0-2 часа":
        feature_vector[3] = 0
    elif answers[3] == "2-4 часа":
        feature_vector[3] = 1
    else:
        feature_vector[3] = 2

    if answers[4] == "Улучшение физической формы":
        feature_vector[4] = 0
    elif answers[4] == "Общение":
        feature_vector[4] = 1
    elif answers[4] == "Соревнование":
        feature_vector[4] = 2
    else:
        feature_vector[4] = 3

    if answers[5] == "На открытом воздухе":
        feature_vector[5] = 0
    else:
        feature_vector[5] = 1

    if answers[6] == "Координация и ловкость":
        feature_vector[6] = 0
    else:
        feature_vector[6] = 1

    if answers[7] == "Да":
        feature_vector[7] = 1
    else:
        feature_vector[7] = 0
    return feature_vector


def set_user_state(chat_id, state, command=None):
    user_data.setdefault(chat_id, {})['state'] = state
    if command:
        user_data[chat_id]['command'] = command


def get_user_state(chat_id):
    return user_data.get(chat_id, {}).get('state')


def get_user_command(chat_id):
    return user_data.get(chat_id, {}).get('command')


def clear_user_data(chat_id):
    if chat_id in user_data:
        del user_data[chat_id]


def ask_question(chat_id, question_index):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    if question_index == 0:
        markup.add("Низкий", "Средний", "Высокий")
    elif question_index == 1:
        markup.add("Индивидуальный", "Командный")
    elif question_index == 2:
        markup.add("Низкая", "Средняя", "Высокая")
    elif question_index == 3:
        markup.add("0-2 часа", "2-4 часа", "4+ часа")
    elif question_index == 4:
        markup.add("Улучшение физической формы", "Общение", "Соревнование", "Снятие стресса")
    elif question_index == 5:
        markup.add("На открытом воздухе", "В помещении")
    elif question_index == 6:
        markup.add("Координация и ловкость", "Силовой")
    elif question_index == 7:
        markup.add("Да", "Нет")
    bot.send_message(chat_id, questions[question_index], reply_markup=markup)


def ask_goal(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Похудение", "Поддержание формы", "Набор массы")
    bot.send_message(chat_id, "Какова ваша цель по питанию?", reply_markup=markup)
    set_user_state(chat_id, 'waiting_for_goal', command='k')


def ask_activity_level(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Низкий", "Средний", "Высокий")
    bot.send_message(chat_id, "Какой у вас уровень активности?", reply_markup=markup)
    set_user_state(chat_id, 'waiting_for_activity', command='k')


def get_organizations_info(sport_type):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT organization, description, phone, address FROM organizations WHERE sport_type=?",
                   (sport_type,))
    organizations = cursor.fetchall()
    conn.close()
    return organizations


@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    if chat_id in user_answers:
        del user_answers[chat_id]
    set_user_state(chat_id, None)

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_data';")
    table_exists = cursor.fetchone()
    if not table_exists:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_data (
            chat_id INTEGER PRIMARY KEY,
            gender TEXT,
            age INTEGER,
            height INTEGER,
            weight REAL,
            activity_level TEXT,
            goal TEXT
        )
        """)
        conn.commit()
        print("Таблица user_data успешно создана.")

    cursor.execute("SELECT chat_id FROM user_data WHERE chat_id=?", (chat_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute("INSERT INTO user_data (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        print(f"Новый пользователь добавлен в базу данных: {chat_id}")
    conn.close()

    bot.send_message(chat_id,
                     "Привет!👋 Я бот, который поможет тебе подобрать спортивные объекты 🏀 в Сургуте 🍽️, подходящий вид спорта 🏀 и рассчитать КБЖУ 🍽️. Выберите, что вы хотите сделать:",
                     reply_markup=get_main_menu())


@bot.message_handler(func=lambda message: message.text == "Найти спортзал")
def gym_command(message):
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT sport_type FROM organizations")
    sport_types = [row[0] for row in cursor.fetchall() if row[0] is not None]
    conn.close()

    for sport in sport_types:
        markup.add(sport)

    bot.send_message(chat_id, "Какой вид спорта вас интересует?", reply_markup=markup)
    bot.register_next_step_handler(message, process_sport_type)


def process_sport_type(message):
    chat_id = message.chat.id
    sport_type = message.text

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    districts = get_surgut_districts()
    for district in districts:
        markup.add(str(district))

    markup.add("Любой район")
    bot.send_message(chat_id, "В каком районе вы ищете спортивный объект?", reply_markup=markup)
    bot.register_next_step_handler(message, lambda msg, s_type=sport_type: process_district(msg, s_type))


def process_district(message, sport_type):
    chat_id = message.chat.id
    district = message.text
    if district == "Любой район":
        district = None
    facilities = get_sports_facilities(district, sport_type)
    if facilities:
        response_text = "Вот спортивные объекты, соответствующие вашим критериям:\n\n"
        for facility in facilities:
            response_text += format_facility_info(facility)
        bot.send_message(chat_id, response_text, parse_mode="Markdown", reply_markup=get_main_menu())
    else:
        bot.send_message(chat_id, "К сожалению, ничего не найдено.", reply_markup=get_main_menu())


@bot.message_handler(commands=['sport'])
def sport(message):
    chat_id = message.chat.id
    user_answers[chat_id] = []
    set_user_state(chat_id, 'sport_question', command='sport')
    bot.send_message(chat_id,
                     "Ответьте, пожалуйста, на несколько вопросов, чтобы я подобрал вам подходящий вид спорта.")
    ask_question(chat_id, 0)


@bot.message_handler(commands=['gender'])
def k(message):
    chat_id = message.chat.id
    set_user_state(chat_id, 'waiting_for_gender', command='k')
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Мужской", "Женский")
    bot.send_message(chat_id, "Укажите ваш пол:", reply_markup=markup)


def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Найти спортзал", "Подобрать вид спорта", "Рассчитать КБЖУ")
    return markup


@bot.message_handler(func=lambda message: get_user_state(message.chat.id) == 'waiting_for_gender')
def gender_step(message):
    chat_id = message.chat.id
    gender = message.text.lower()
    if gender not in ("мужской", "женский"):
        bot.send_message(chat_id, "Пожалуйста, укажите пол: мужской или женский.")
        return
    user_data.setdefault(chat_id, {})['gender'] = gender
    set_user_state(chat_id, 'waiting_for_age', command=get_user_command(chat_id))
    bot.send_message(chat_id, "Укажите ваш возраст (полных лет):", reply_markup=types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda message: get_user_state(message.chat.id) == 'waiting_for_age')
def age_step(message):
    chat_id = message.chat.id
    try:
        age = int(message.text)
        if age <= 0 or age > 120:
            bot.send_message(chat_id, "Пожалуйста, укажите корректный возраст (от 1 до 120):")
            return
        user_data[chat_id]['age'] = age
        set_user_state(chat_id, 'waiting_for_height', command=get_user_command(chat_id))
        bot.send_message(chat_id, "Укажите ваш рост в сантиметрах:")
    except ValueError:
        bot.send_message(chat_id, "Пожалуйста, укажите возраст числом.")


@bot.message_handler(func=lambda message: get_user_state(message.chat.id) == 'waiting_for_height')
def height_step(message):
    chat_id = message.chat.id
    try:
        height = int(message.text)
        if height <= 50 or height > 250:
            bot.send_message(chat_id, "Пожалуйста, укажите корректный рост (от 50 до 250 см):")
            return
        user_data[chat_id]['height'] = height
        set_user_state(chat_id, 'waiting_for_weight', command=get_user_command(chat_id))
        bot.send_message(chat_id, "Укажите ваш вес в килограммах:")
    except ValueError:
        bot.send_message(chat_id, "Пожалуйста, укажите рост числом.")


@bot.message_handler(func=lambda message: get_user_state(message.chat.id) == 'waiting_for_weight')
def weight_step(message):
    chat_id = message.chat.id
    try:
        weight = float(message.text)
        if weight <= 20 or weight > 300:
            bot.send_message(chat_id, "Пожалуйста, укажите корректный вес (от 20 до 300 кг):")
            return
        user_data[chat_id]['weight'] = weight
        ask_activity_level(chat_id)
    except ValueError:
        bot.send_message(chat_id, "Пожалуйста, укажите вес числом.")


@bot.message_handler(func=lambda message: get_user_state(message.chat.id) == 'waiting_for_activity')
def activity_step(message):
    chat_id = message.chat.id
    activity_level = message.text.lower()
    if activity_level not in activity_factors:
        bot.send_message(chat_id, "Пожалуйста, выберите уровень активности из предложенных вариантов.")
        return
    user_data[chat_id]['activity_level'] = activity_level
    ask_goal(chat_id)


@bot.message_handler(func=lambda message: get_user_state(message.chat.id) == 'waiting_for_goal')
def goal_step(message):
    chat_id = message.chat.id
    goal = message.text.lower()
    if goal not in ("похудение", "поддержание формы", "набор массы"):
        bot.send_message(chat_id, "Пожалуйста, выберите цель из предложенных вариантов.")
        return
    user_data[chat_id]['goal'] = goal

    calories_data = calculate_calories(
        gender=user_data[chat_id]['gender'],
        weight=user_data[chat_id]['weight'],
        height=user_data[chat_id]['height'],
        age=user_data[chat_id]['age'],
        activity_level=user_data[chat_id]['activity_level'],
        goal=user_data[chat_id]['goal']
    )

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE user_data SET 
        gender=?, 
        age=?, 
        height=?, 
        weight=?, 
        activity_level=?, 
        goal=?
    WHERE chat_id=?
    """, (user_data[chat_id]['gender'],
          user_data[chat_id]['age'],
          user_data[chat_id]['height'],
          user_data[chat_id]['weight'],
          user_data[chat_id]['activity_level'],
          user_data[chat_id]['goal'],
          chat_id))
    conn.commit()
    conn.close()

    response_text = f"Ваши рекомендации по КБЖУ:\n"
    response_text += f"Калории: {calories_data['калории']}\n"
    response_text += f"Белки: {calories_data['белки']} г\n"
    response_text += f"Жиры: {calories_data['жиры']} г\n"
    response_text += f"Углеводы: {calories_data['углеводы']} г"

    bot.send_message(chat_id, response_text, reply_markup=get_main_menu())
    clear_user_data(chat_id)


@bot.message_handler(func=lambda message: message.text in ["Подобрать вид спорта", "Рассчитать КБЖУ",
                                                           "Найти спортзал"])
def main_menu_handler(message):
    chat_id = message.chat.id
    choice = message.text

    if choice == "Подобрать вид спорта":
        sport(message)
    elif choice == "Рассчитать КБЖУ":
        k(message)
    elif choice == "Найти спортзал":
        gym_command(message)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    state = get_user_state(chat_id)
    command = get_user_command(chat_id)

    if state == 'sport_question':
        user_answers.setdefault(chat_id, []).append(message.text)
        question_index = len(user_answers[chat_id])

        if question_index < len(questions):
            ask_question(chat_id, question_index)
        else:
            feature_vector = process_answers(user_answers[chat_id])
            predicted_sport = predict_sport(feature_vector)
            organizations = get_organizations_info(predicted_sport)

            if organizations:
                response_text = f"На основе ваших ответов, я рекомендую вам заниматься: {predicted_sport} 🎉\n\nВот организации, которые могут вам подойти:\n\n"
                for org in organizations:
                    response_text += f"🏢 *{org[0]}*\n"
                    response_text += f"📝 Описание: {org[1]}\n"
                    response_text += f"📞 Телефон: {org[2] if org[2] else 'Не указан'}\n"
                    response_text += f"📍 Адрес: {org[3]}\n\n"
            else:
                response_text = f"Я рекомендую вам {predicted_sport}, но, к сожалению, у меня нет информации об организациях для этого вида спорта."

            bot.send_message(chat_id, response_text, parse_mode="Markdown", reply_markup=get_main_menu())

            del user_answers[chat_id]
            clear_user_data(chat_id)
            user_data.pop(chat_id, None)
    elif command == 'k':
        if state in (
                'waiting_for_gender', 'waiting_for_age', 'waiting_for_height', 'waiting_for_weight',
                'waiting_for_activity',
                'waiting_for_goal'):
            if state == 'waiting_for_gender':
                gender_step(message)
            elif state == 'waiting_for_age':
                age_step(message)
            elif state == 'waiting_for_height':
                height_step(message)
            elif state == 'waiting_for_weight':
                weight_step(message)
            elif state == 'waiting_for_activity':
                activity_step(message)
            elif state == 'waiting_for_goal':
                goal_step(message)
    elif message.text == "Найти спортзал":
        gym_command(message)
    elif message.text == "Подобрать вид спорта":
        sport(message)
    elif message.text == "Рассчитать КБЖУ":
        k(message)
    else:
        bot.send_message(chat_id, "Используйте кнопки меню или команды /start, /k или /sport")


def send_reminder():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_data';")
    table_exists = cursor.fetchone()

    if table_exists:
        cursor.execute("SELECT DISTINCT chat_id FROM user_data")
        users = cursor.fetchall()
        for user in users:
            chat_id = user[0]
            reminder = random.choice(reminders)
            try:
                bot.send_message(chat_id, reminder)
                print(f"Напоминание отправлено пользователю {chat_id} в {datetime.datetime.now()}")
            except Exception as e:
                print(f"Не удалось отправить напоминание пользователю {chat_id}: {e}")
    else:
        print("Таблица user_data не существует. Рассылка невозможна.")

    conn.close()


def setup_schedule():
    sched.every().day.at("09:51").do(send_reminder)


def run_scheduler():
    while True:
        sched.run_pending()
        time.sleep(1)


def create_tables():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization TEXT NOT NULL,
                sport_type TEXT NOT NULL,
                district TEXT,
                address TEXT,
                phone TEXT,
                website TEXT,
                description TEXT
            )
            ''')

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_data (
                chat_id INTEGER PRIMARY KEY,
                gender TEXT,
                age INTEGER,
                height INTEGER,
                weight REAL,
                activity_level TEXT,
                goal TEXT
            )
            ''')
    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    print("Checking for 'district' column...")
    cursor.execute("PRAGMA table_info(organizations)")
    columns = [column[1] for column in cursor.fetchall()]
    print(f"Columns found: {columns}")
    if 'district' not in columns:
        print("'district' column not found. Adding it...")
        cursor.execute("ALTER TABLE organizations ADD COLUMN district TEXT")
    else:
        print("'district' column found.")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    print("Checking for 'description' column...")
    cursor.execute("PRAGMA table_info(organizations)")
    columns = [column[1] for column in cursor.fetchall()]
    print(f"Columns found: {columns}")
    if 'description' not in columns:
        print("'description' column not found. Adding it...")
        cursor.execute("ALTER TABLE organizations ADD COLUMN description TEXT")
    else:
        print("'description' column found.")
    conn.commit()
    conn.close()

    threading.Thread(target=setup_schedule).start()
    threading.Thread(target=run_scheduler, daemon=True).start()

    bot.infinity_polling()
