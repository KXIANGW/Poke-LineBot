import sys
import configparser
import os, tempfile

from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage,
    VideoMessage
)
from linebot.v3.messaging.models.sticker_message import StickerMessage
from linebot.v3.messaging.models.location_message import LocationMessage

# Gemini API SDK
import google.generativeai as genai

# image processing
import PIL

from collections import defaultdict

#Config Parser
config = configparser.ConfigParser()
config.read('config.ini')

# Gemini API Settings
genai.configure(api_key=config["Gemini"]["API_KEY"])

llm_role_description = """
你是一位神奇寶貝中的女性角色「莉莉艾」，個性與回覆內容與該女角一樣，並準確地回答使用者的問題或內容。
"""

# Check available models
'''
print("Available models:")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(f"{m.name} (Generate Content)")
    else:
        print(f"{m.name} (Other purpose)")
'''
# Use the model
from google.generativeai.types import HarmCategory, HarmBlockThreshold
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-latest",
    safety_settings={
        HarmCategory.HARM_CATEGORY_HARASSMENT:HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH:HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT:HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT:HarmBlockThreshold.BLOCK_NONE,
    },
    generation_config={
        "temperature": 1,   # 活潑
        "top_p": 0.95,
        "top_k": 64,
        "max_output_tokens": 1000,  # 廢話
    },
    system_instruction=llm_role_description,
)


UPLOAD_FOLDER = "static"
app = Flask(__name__)

channel_access_token = config['Line']['CHANNEL_ACCESS_TOKEN']
channel_secret = config['Line']['CHANNEL_SECRET']
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # parse webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

chat_history = defaultdict(list)
@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    user_id = event.source.user_id
    user_input = event.message.text
    if event.message.text[0] == '~':
        message = process_command(user_input[1:])
        bot_reply = message.text if isinstance(message, TextMessage) else "[非文字回應]"
    else:
        bot_reply = gemini_llm_sdk(user_input)
        message = TextMessage(text=bot_reply)

    chat_history[user_id].append({
    "user": user_input,
    "bot": bot_reply
    })

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[message],
            )
        )

def process_command(command: str):
    if command == "文字":
        return TextMessage(text='我是莉莉艾，請問有什麼問題呢？')
    elif command == "貼圖":
        return StickerMessage(package_id='11537', sticker_id='52002734')
    elif command == "圖片":
        return ImageMessage(original_content_url='https://truth.bahamut.com.tw/s01/202504/forum/79688/6cf4fbd593fc0a607b7ccf6fe16dfa57.JPG', preview_image_url='https://truth.bahamut.com.tw/s01/202504/forum/79688/6cf4fbd593fc0a607b7ccf6fe16dfa57.JPG')
    elif command == "影片":
        return VideoMessage(original_content_url='https://kxiangw.github.io/Poke-LineBot/static/%E8%8E%89%E8%8E%89%E8%89%BE.mp4', preview_image_url='https://truth.bahamut.com.tw/s01/202504/forum/79688/6cf4fbd593fc0a607b7ccf6fe16dfa57.JPG')
    elif command == "位置資訊":
        return LocationMessage(title='YZU', address='320桃園市中壢區遠東路135號', latitude=24.96861, longitude=121.26611)
    elif command.startswith("情緒分析"):
        # Bonus: 情緒分析
        user_input = command.replace("情緒分析", "", 1).strip()
        prompt = f"""
                請分析以下句子的情緒傾向，並以這個格式輸出：
                分析結果：[-正向 / -中性 / -負向]
                理由：[簡單一句話說明情緒判斷的原因]

                句子：
                {user_input}
                """
        return TextMessage(text=gemini_llm_sdk(prompt))
    else:
        return TextMessage(text='無效的指令')

image_file = []
index = 0

def gemini_llm_sdk(user_input):
    try:
        response = model.generate_content(user_input)
        print(f"Question: {user_input}")
        print(f"Answer: {response.text}")
        return response.text.strip()
    except Exception as e:
        print(e)
        return "Gemini robot故障中！"
    
# 儲存歷史對話、刪除歷史對話(需撰寫RESTful GET/DELETE API)
from flask import jsonify
@app.route("/history/<user_id>", methods=['GET'])
def get_history(user_id):
    history = chat_history.get(user_id)
    if history:
        return jsonify(history), 200
    else:
        return jsonify({"message": "No history found for this user."}), 404
    
@app.route("/history/<user_id>", methods=['DELETE'])
def delete_history(user_id):
    if user_id in chat_history:
        del chat_history[user_id]
        return jsonify({"message": f"History for user {user_id} deleted."}), 200
    else:
        return jsonify({"message": "No history found to delete."}), 404
    
@app.route("/history/all_user", methods=['GET'])
def get_all_history():
    if chat_history:
        return jsonify(chat_history), 200
    else:
        return jsonify({"message": "No chat history found."}), 404
    
@app.route("/history/all_user", methods=['DELETE'])
def delete_all_history():
    chat_history.clear()
    return jsonify({"message": "All user histories have been deleted."}), 200



if __name__ == "__main__":
    app.run()