import os
import json
from flask import Flask, render_template, request, jsonify
from google import genai
from google.genai import errors
from dotenv import load_dotenv

# .envファイルからAPIキーを読み込む
load_dotenv()

app = Flask(__name__)

# Gemini APIクライアントの設定
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


@app.route("/")
def index() -> str:
    # トップページを表示する
    return render_template("index.html")


@app.route("/brainstorm", methods=["POST"])
def brainstorm() -> tuple:
    # フロントから送られたキーワードを受け取る
    data: dict = request.get_json()
    keyword: str = data.get("keyword", "")

    # キーワードが空の場合はエラーを返す
    if not keyword:
        return jsonify({"error": "キーワードを入力してください"}), 400

    # Geminiに送るプロンプトを作成する
    prompt: str = f"""
#指示
「{keyword}」に関するキーワードを20個、カテゴリに分類して出力してください。

#出力形式（必ずこのJSON形式で返すこと。それ以外のテキストは不要）
{{
  "categories": [
    {{
      "name": "カテゴリ名",
      "ideas": ["アイデア1", "アイデア2"]
    }}
  ]
}}

#ルール
・カテゴリは最大5個
・合計アイデア数は20個
・どのカテゴリにも当てはまらない場合は新しいカテゴリ名を作る
"""

    try:
        # Gemini APIにプロンプトを送信する
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        # 返答からJSON部分だけを取り出してパースする
        text: str = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result: dict = json.loads(text)
        return jsonify(result), 200

    except errors.ClientError as e:
        # APIキーの問題・無料枠オーバーなどのエラー
        return jsonify({
            "error": "api_limit",
            "message": "無料枠の上限に達しました。しばらく待ってから再試行してください。"
        }), 429

    except errors.ServerError as e:
        # サーバー混雑などのエラー
        return jsonify({
            "error": "server_busy",
            "message": "AIサーバーが混雑しています。少し待ってから再試行してください。"
        }), 503

    except Exception as e:
        # その他の予期しないエラー
        return jsonify({
            "error": "unknown",
            "message": "予期しないエラーが発生しました。もう一度試してください。"
        }), 500


if __name__ == "__main__":
    app.run(debug=True)