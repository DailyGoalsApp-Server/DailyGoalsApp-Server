from flask import Flask, jsonify, request

from generator import draw


app = Flask(__name__)

@app.route('/generate', methods=['POST'])
def generate():
    try:
        raw_data = request.data.decode('utf-8')  # 手動解碼為 UTF-8
        print("Raw Data:", raw_data)  # 打印出原始資料
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        sex = data.get("sex")
        age_range = data.get("age_range")
        intensity = data.get("intensity")
        height_range= data.get("height_range")
        weight_range = data.get("weight_range")

        print(intensity)
        
        if not sex or not age_range or not intensity or not height_range or not weight_range:
            return jsonify({"error": "Missing required fields (sex, age_range, intensity)"}), 400
        
        result = draw(sex, age_range, intensity,height_range,weight_range)

        # 生成任务的逻辑 (示例返回固定结果)
        task = result['task']
        hints = result['hints']
        
        response = {
            "task": task,
            "hints": hints
        }
        
        return jsonify(response), 200  

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)  

