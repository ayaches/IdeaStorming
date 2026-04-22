import os
import json
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from google import genai
from google.genai import errors
from dotenv import load_dotenv
from datetime import datetime

# .envファイルからAPIキーを読み込む
load_dotenv()

app = Flask(__name__)

# データベースの設定
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ideastorming.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)

# Gemini APIクライアントの設定
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# プロジェクトテーブルの定義
class Project(db.Model):
    __tablename__ = "projects"

    id: int = db.Column(db.Integer, primary_key=True)
    title: str = db.Column(db.String(200), nullable=False)
    keyword: str = db.Column(db.String(200), nullable=False)
    result: str = db.Column(db.Text, nullable=False)
    is_favorite: bool = db.Column(db.Boolean, default=False)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow)


# アプリ起動時にテーブルを作成する
with app.app_context():
    db.create_all()


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
      "ideas": ["キーワード1", "キーワード2"]
    }}
  ]
}}

#ルール
・カテゴリは最大5個
・合計キーワード数は20個
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

    except errors.ClientError:
        return jsonify({
            "error": "api_limit",
            "message": "無料枠の上限に達しました。しばらく待ってから再試行してください。"
        }), 429

    except errors.ServerError:
        return jsonify({
            "error": "server_busy",
            "message": "AIサーバーが混雑しています。少し待ってから再試行してください。"
        }), 503

    except Exception:
        return jsonify({
            "error": "unknown",
            "message": "予期しないエラーが発生しました。もう一度試してください。"
        }), 500


@app.route("/save", methods=["POST"])
def save() -> tuple:
    # フロントから送られたデータを受け取る
    data: dict = request.get_json()
    keyword: str = data.get("keyword", "")
    result: str = data.get("result", "")

    # キーワードが空の場合はエラーを返す
    if not keyword or not result:
        return jsonify({"error": "保存するデータがありません"}), 400

    # タイトルはキーワードをそのまま使う
    new_project = Project(
        title=keyword,
        keyword=keyword,
        result=json.dumps(result, ensure_ascii=False)
    )

    db.session.add(new_project)
    db.session.commit()

    return jsonify({"message": "保存しました", "id": new_project.id}), 200


@app.route("/projects", methods=["GET"])
def get_projects() -> tuple:
    # 保存済みプロジェクトを新しい順に取得する
    projects: list = Project.query.order_by(Project.created_at.desc()).all()

    result: list = [
        {
            "id": p.id,
            "title": p.title,
            "keyword": p.keyword,
            "created_at": p.created_at.strftime("%Y/%m/%d %H:%M")
        }
        for p in projects
    ]

    return jsonify(result), 200


@app.route("/projects/<int:project_id>", methods=["DELETE"])
def delete_project(project_id: int) -> tuple:
    # 指定されたIDのプロジェクトを削除する
    project = Project.query.get(project_id)

    if not project:
        return jsonify({"error": "プロジェクトが見つかりません"}), 404

    db.session.delete(project)
    db.session.commit()

    return jsonify({"message": "削除しました"}), 200


if __name__ == "__main__":
    app.run(debug=True)