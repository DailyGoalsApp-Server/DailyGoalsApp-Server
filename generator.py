from threading import RLock
from concurrent.futures import ThreadPoolExecutor
import json, random, os
from dotenv import load_dotenv
from flask import Flask
import google.generativeai as genai
from flask_sqlalchemy import SQLAlchemy
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

load_dotenv()
API_KEY = os.getenv("API_KEY")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///challenges.db'  
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy()
db.init_app(app)
app.secret_key = os.urandom(24)

challenge_locks = {}

def get_or_create_lock(challenge_id, write_lock=False):  
    """根據是否是寫操作來選擇讀鎖或寫鎖"""
    if challenge_id not in challenge_locks:
        challenge_locks[challenge_id] = RLock()  # 用 RLock 來支持可重入
    lock = challenge_locks[challenge_id]
    
    if write_lock:
        return lock  # 寫鎖會獨佔鎖
    else:
        return lock  # 讀鎖可以多個線程同時讀取

class Challenge(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task = db.Column(db.String(200), nullable=False)
    hints = db.Column(db.Text, nullable=False)
    intensity = db.Column(db.String(20), nullable=False)
    age_range = db.Column(db.String(20))
    sex = db.Column(db.String(5), nullable=False)

    def __repr__(self):
        return f"<Challenge {self.id}, Task: {self.task}>"

def read_db():
    challenges = Challenge.query.all()
    challenges_dict = {challenge.id: {
        "task": challenge.task,
        "hints": json.loads(challenge.hints),
        "intensity": challenge.intensity,
        "age_range": challenge.age_range,
        "sex": challenge.sex,
        "times": 3
    } for challenge in challenges}
    logging.info(f"Loaded {len(challenges_dict)} challenges from the database.")
    # print(challenges_dict)
    return challenges_dict

with app.app_context():
    db.create_all()
    challenges_dict = read_db()

def generate(sex, age_range, intensity):
    dietary_challenge_list = ["飲食", "喝水", "蔬菜攝入", "減糖", "低GI", "水果攝入", "低卡餐"]
    sport_challenge_list = ["運動", "快走", "慢跑", "瑜伽", "力量訓練", "爬樓梯", "自行車"]
    challenge_type = random.choice(["運動", "飲食", "生活習慣"])

    if challenge_type == "運動":
        challenge = random.choice(sport_challenge_list)
    elif challenge_type == "飲食":
        challenge = random.choice(dietary_challenge_list)
    else:
        challenge = "生活習慣"

    prompt = (
        f"請設計一個一日可完成的{challenge}小挑戰，只需要完成一件事。挑戰對象為{age_range}{sex}，平常運動強度為{intensity}，該挑戰需對於挑戰對象來說是可達成的。"
        f"請以JSON格式輸出，格式為：{{\"TASK\":{{\"content\":\"挑戰內容\"}}, \"HINT\":{{\"content\":[\"提示1\",\"提示2\",...]}}}}。"
        f"生成內容請控制在200個字內。"
    )

    generation_config = {"temperature": 1}
    genai.configure(api_key=API_KEY)

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt, generation_config=generation_config)
        response_text = response.text.replace("```json", "").replace("```", "")
        data = json.loads(response_text)
        task = data["TASK"]["content"]
        hints = data["HINT"]["content"]
    except Exception as e:
        logging.error(f"Failed to generate challenge: {e}")
        return None

    if not task or not hints:
        logging.error("Generated challenge is incomplete.")
        return None

    with app.app_context(): 
        id = write_db(sex, age_range, intensity, task, hints)
        
    challenge_data = {
        'task': task,
        'hints': hints,
        'intensity': intensity,
        'age_range': age_range,
        'sex': sex,
        'times': 4
    }

    with get_or_create_lock(sex + age_range + intensity, write_lock=True):
        challenges_dict[id] = challenge_data

    return {id: challenge_data}

def write_db(sex, age_range, intensity, task, hints):
    hints_str = json.dumps(hints)  
    new_challenge = Challenge(
        task=task,
        hints=hints_str,
        intensity=intensity,
        age_range=age_range,
        sex=sex
    )
    db.session.add(new_challenge)
    db.session.commit()
    return new_challenge.id

def delete_expired_challenges(): 
    expired_challenges = Challenge.query.filter(Challenge.times < 1).all()
    for challenge in expired_challenges:
        db.session.delete(challenge)
    db.session.commit()
    logging.info(f"Deleted {len(expired_challenges)} expired challenges.")

def draw(sex, age_range, intensity):
    global challenges_dict

    filtered_challenges = {
        key: value for key, value in challenges_dict.items()
        if value['sex'] == sex and value['age_range'] == age_range and value['intensity'] == intensity
    }

    if len(filtered_challenges) == 0:
        new_challenge = generate(sex, age_range, intensity)
        with get_or_create_lock(sex + age_range + intensity, write_lock=True):
            challenges_dict.update(new_challenge)
        return {
            "task": list(new_challenge.values())[0]['task'],
            "hints": list(new_challenge.values())[0]['hints']
        }

    random_key = random.choice(list(filtered_challenges.keys()))
    challenge = challenges_dict[random_key]

    with get_or_create_lock(random_key):
        challenges_dict[random_key]["times"] -= 1
        if challenges_dict[random_key]["times"] < 1:
            delete_expired_challenges()
            new_challenge = generate(sex, age_range, intensity)
            challenges_dict.update(new_challenge)

    return {"task": challenge['task'], "hints": challenge['hints']}


if __name__ == "__main__":
    with app.app_context():
        data = draw(sex="女性", age_range="15-20", intensity="低強度")
        print(data['task'])
        print(data['hints'])
