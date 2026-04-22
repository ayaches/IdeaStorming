import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from google import genai
from google.genai import errors
from dotenv import load_dotenv
from datetime import datetime
import bcrypt

# .envファイルからAPIキーを読み込む
load_dotenv()

app = Flask(__name__)

# データベースの設定
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ideastorming.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

db = SQLAlchemy(app)

# ログインマネージャーの設定
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# Gemini APIクライアントの設定
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ユーザーテーブルの定義
class User(UserMixin, db.Model):
    __tablename__ = "users"
    __allow_unmapped__ = True

    id: int = db.Column(db.Integer, primary_key=True)
    email: str = db.Column(db.String(200), unique=True, nullable=False)
    password: str = db.Column(db.String(200), nullable=False)
    projects: list = db.relationship("Project", backref="user", lazy=True)

# プロジェクトテーブルの定義
class Project(db.Model):
    __tablename__ = "projects"

    id: int = db.Column(db.Integer, primary_key=True)
    title: str = db.Column(db.String(200), nullable=False)
    keyword: str = db.Column(db.String(200), nullable=False)
    result: str = db.Column(db.Text, nullable=False)
    is_favorite: bool = db.Column(db.Boolean, default=False)
    created_at: datetime = db.Column(db.DateTime, default=datetime.utcnow)
    user_id: int = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


# アプリ起動時にテーブルを作成する
with app.app_context():
    db.create_all()


# ログインマネージャーにユーザー取得方法を教える
@login_manager.user_loader
def load_user(user_id: str) -> User:
    return User.query.get(int(user_id))


# トップページ（ログイン必須）
@app.route("/")
@login_required
def index() -> str:
    return render_template("index.html")


# 会員登録ページ
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    # フォームからメールとパスワードを受け取る
    data: dict = request.get_json()
    email: str = data.get("email", "")
    password: str = data.get("password", "")

    # 入力チェック
    if not email or not password:
        return jsonify({"error": "メールアドレスとパスワードを入力してください"}), 400

    # すでに登録済みのメールアドレスか確認する
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"error": "このメールアドレスはすでに登録されています"}), 400

    # パスワードをハッシュ化して保存する
    hashed_password: bytes = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    new_user = User(
        email=email,
        password=hashed_password.decode("utf-8")
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "登録しました"}), 200


# ログインページ
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # フォームからメールとパスワードを受け取る
    data: dict = request.get_json()
    email: str = data.get("email", "")
    password: str = data.get("password", "")

    # ユーザーを検索する
    user = User.query.filter_by(email=email).first()

    # パスワードを照合する
    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password.encode("utf-8")):
        return jsonify({"error": "メールアドレスまたはパスワードが違います"}), 401

    login_user(user)
    return jsonify({"message": "ログインしました"}), 200


# ログアウト
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ブレインストーム実行
@app.route("/brainstorm", methods=["POST"])
@login_required
def brainstorm() -> tuple:
    data: dict = request.get_json()
    keyword: str = data.get("keyword", "")

    if not keyword:
        return jsonify({"error": "キーワードを入力してください"}), 400

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
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

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


# プロジェクトを保存する
@app.route("/save", methods=["POST"])
@login_required
def save() -> tuple:
    data: dict = request.get_json()
    keyword: str = data.get("keyword", "")
    result = data.get("result", "")

    if not keyword or not result:
        return jsonify({"error": "保存するデータがありません"}), 400

    new_project = Project(
        title=keyword,
        keyword=keyword,
        result=json.dumps(result, ensure_ascii=False),
        user_id=current_user.id
    )

    db.session.add(new_project)
    db.session.commit()

    return jsonify({"message": "保存しました", "id": new_project.id}), 200


# 自分のプロジェクト一覧を取得する
@app.route("/projects", methods=["GET"])
@login_required
def get_projects() -> tuple:
    projects: list = Project.query.filter_by(user_id=current_user.id)\
        .order_by(Project.created_at.desc()).all()

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


# プロジェクトを削除する
@app.route("/projects/<int:project_id>", methods=["DELETE"])
@login_required
def delete_project(project_id: int) -> tuple:
    project = Project.query.filter_by(id=project_id, user_id=current_user.id).first()

    if not project:
        return jsonify({"error": "プロジェクトが見つかりません"}), 404

    db.session.delete(project)
    db.session.commit()

    return jsonify({"message": "削除しました"}), 200

# ゲスト用トップページ（ログイン不要）
@app.route("/guest")
def guest() -> str:
    return render_template("index.html", is_guest=True)


# ゲスト用ブレインストーム（ログイン不要）
@app.route("/brainstorm/guest", methods=["POST"])
def brainstorm_guest() -> tuple:
    data: dict = request.get_json()
    keyword: str = data.get("keyword", "")

    if not keyword:
        return jsonify({"error": "キーワードを入力してください"}), 400

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
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

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
    
if __name__ == "__main__":
    app.run(debug=True)