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
    task_content = db.Column(db.String(200), nullable=False)
    hint_content = db.Column(db.Text, nullable=False)
    intensity = db.Column(db.String(20), nullable=False)
    age_range = db.Column(db.String(20))
    sex = db.Column(db.String(5), nullable=False)

    def __repr__(self):
        return f"<Challenge {self.id}, Task: {self.task_content}>"

def read_db():
    challenges = Challenge.query.all()
    challenges_dict = {challenge.id: {
        "task_content": challenge.task_content,
        "hint_content": json.loads(challenge.hint_content),
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
        task_content = data["TASK"]["content"]
        hint_content = data["HINT"]["content"]
    except Exception as e:
        logging.error(f"Failed to generate challenge: {e}")

    with app.app_context(): 
        id = write_db(sex, age_range, intensity, task_content, hint_content)
        
    challenge_data = {
        "task_content": task_content,
        "hint_content": hint_content,
        "intensity": intensity,
        "age_range": age_range,
        "sex": sex,
        "times": 4
    }
    challenges_dict[id] = challenge_data
    print("生成成功")
    return {id: challenge_data}

def write_db(sex, age_range, intensity, task_content, hint_content):
    hint_content_str = json.dumps(hint_content)  
    new_challenge = Challenge(
        task_content=task_content,
        hint_content=hint_content_str,
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
    print(len(filtered_challenges) )

    if len(filtered_challenges) == 0:
        new_challenge = generate(sex, age_range, intensity)
        with get_or_create_lock(sex + age_range + intensity, write_lock=True):  # 使用寫鎖，防止多線程寫入
            print("lock 1")
            challenges_dict.update(new_challenge)
        print("lock 1 relese")
        filtered_challenges = new_challenge
        return {"task": challenge['task_content'], "hint": challenge['hint_content']}


    if len(filtered_challenges) < 10:
        times = 10 - len(filtered_challenges)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(generate, sex, age_range, intensity) for _ in range(times)]
            for future in futures:
                new_challenge = future.result()
                with get_or_create_lock(sex + age_range + intensity, write_lock=True):  # 寫鎖，保證更新
                    print("lock 2")
                    challenges_dict.update(new_challenge)
                    print("lock 2 relese")


    random_key = random.choice(list(filtered_challenges.keys()))
    challenge = challenges_dict[random_key]

    with get_or_create_lock(random_key): 
        print("lock 3")
        challenges_dict[random_key]["times"] -= 1
        if challenges_dict[random_key]["times"] < 1:
            delete_expired_challenges()
            future = generate(sex, age_range, intensity)
            challenges_dict.update(future)
        print("lock 3 relese")

    return {"task": challenge['task_content'], "hint": challenge['hint_content']}

if __name__ == "__main__":
    with app.app_context():
        data = draw(sex="女性", age_range="15-20", intensity="低強度")
        print(data['task'])
        print(data['hint'])
