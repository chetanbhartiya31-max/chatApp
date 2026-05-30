import os
from flask import Flask, request, jsonify, session, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

app = Flask(__name__)

# ========== DATABASE CONFIGURATION WITH LOGGING ==========
print("\n" + "=" * 60)
print("🔧 CHECKING DATABASE CONFIGURATION...")
print("=" * 60)

database_url = os.environ.get("DATABASE_URL")

if database_url:
    print(f"✅ DATABASE_URL found: {database_url[:50]}...")
    
    # Render uses postgres:// but SQLAlchemy requires postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        print("✅ Converted postgres:// to postgresql://")
    
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    print("✅ USING POSTGRESQL DATABASE (Data will PERSIST!)")
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
    print("⚠️ USING SQLITE DATABASE (Data will be LOST on restart!)")

print("=" * 60 + "\n")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.urandom(24)

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=True)

db = SQLAlchemy(app)

# ------------------------- Models -------------------------
user_rooms = db.Table(
    "user_rooms",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id")),
    db.Column("room_id", db.Integer, db.ForeignKey("room.id")),
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    email = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    email_valadity = db.Column(db.Boolean, default=True)
    messages_sent = db.Column(db.Integer, default=0)
    rooms_joined = db.Column(db.Integer, default=0)
    messages = db.relationship("Messages", backref="user")
    rooms = db.relationship("Room", secondary=user_rooms, backref="users")

class Messages(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(1000), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    messages = db.relationship("Messages", backref="room")

# ------------------------- Create tables & seed admin -------------------------
with app.app_context():
    db.create_all()

    # Create global room if not exists
    global_room = Room.query.get(1)
    if global_room is None:
        global_room = Room(
            id=1,
            name="global",
            password_hash=generate_password_hash("global"),
            created_at=datetime.now(),
        )
        db.session.add(global_room)
        db.session.commit()
        print("✅ Global room created")

    # Seed admin user if none exists
    admin_user = User.query.filter_by(is_admin=True).first()
    if not admin_user:
        admin = User(
            username="admin",
            email="admin@gmail.com",
            password_hash=generate_password_hash("chetan1man@"),
            is_admin=True,
            created_at=datetime.now(),
            email_valadity=True,
            messages_sent=0,
            rooms_joined=0
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created: username='admin', password='chetan1man@'")

# ------------------------- Admin decorator -------------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify(message="Not logged in"), 401
        user = User.query.get(user_id)
        if not user or not user.is_admin:
            return jsonify(message="Admin access required"), 403
        return f(*args, **kwargs)
    return decorated_function

# ------------------------- Routes -------------------------
@app.route("/")
def main_page():
    return render_template("auth.html")

@app.route("/room/<int:room_id>")
def chat_room(room_id):
    user_id = session.get("user_id")
    if not user_id:
        return render_template("auth.html")
    return render_template("room.html", room_id=room_id)

@app.route("/dashboard")
def dashboard():
    user_id = session.get("user_id")
    if not user_id:
        return render_template("auth.html")
    user = User.query.get(user_id)
    if user is None:
        return render_template("auth.html")
    created_for = datetime.now() - user.created_at
    messages_sent = user.messages_sent
    rooms_joined = len(user.rooms)
    return render_template(
        "dashboard.html",
        username=user.username,
        email=user.email,
        created_at=user.created_at.strftime("%B %d, %Y"),
        created_for=created_for.days,
        messages_sent=messages_sent,
        rooms_joined=rooms_joined,
        is_admin=user.is_admin,
    )

@app.route("/auth/signup", methods=["POST"])
def sign_up():
    data = request.get_json()
    if not data:
        return jsonify(message="No data provided"), 400
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    if username is None or len(username) > 30 or len(username) < 3:
        return jsonify(message="Invalid username"), 400
    if not ("@" in email and email.count("@") == 1 and "." in email and email.count(".") >= 1):
        return jsonify(message="Invalid email"), 400
    if password is None or len(password) > 30 or len(password) < 6:
        return jsonify(message="Invalid password"), 400
    hashed_password = generate_password_hash(password)
    if User.query.filter_by(username=username).first() is not None:
        return jsonify(message="Username already exists"), 400
    if User.query.filter_by(email=email).first() is not None:
        return jsonify(message="Email already exists"), 400

    user = User(
        username=username,
        email=email,
        password_hash=hashed_password,
        is_admin=False,
        created_at=datetime.now(),
        email_valadity=True,
        messages_sent=0,
        rooms_joined=0,
    )
    db.session.add(user)
    db.session.commit()

    global_room = Room.query.get(1)
    if global_room and global_room not in user.rooms:
        user.rooms.append(global_room)
        user.rooms_joined = len(user.rooms)
        db.session.commit()

    return jsonify({"user": username, "email": email, "created_at": user.created_at}), 200

@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify(message="No data provided"), 400
    username = data.get("username")
    password = data.get("password")
    user = User.query.filter_by(username=username).first()
    if user is None:
        return jsonify(message="Invalid password or username"), 400
    if not check_password_hash(user.password_hash, password):
        return jsonify(message="Invalid password or username"), 400
    if not user.email_valadity:
        return jsonify(message="Email not validated"), 400
    session["user_id"] = user.id
    session["username"] = user.username
    session["is_admin"] = user.is_admin
    return jsonify(message="User logged in successfully"), 200

@socketio.on("send_messages")
def handle_send_message(data):
    user_id = session.get("user_id")
    if user_id is None:
        emit("error", {"message": "User not logged in"})
        return
    content = data.get("content")
    room_id = data.get("room_id")
    room = Room.query.get(room_id)
    if room is None:
        emit("error", {"message": "Room not found"})
        return
    if content is None or len(content) > 1000 or len(content) < 1 or content.strip() == "":
        emit("error", {"message": "Invalid message"})
        return
    message = Messages(content=content, user_id=user_id, room_id=room_id, created_at=datetime.now())
    db.session.add(message)
    db.session.commit()
    user = User.query.get(user_id)
    if not user:
        emit("error", {"message": "User not found"})
        return
    user.messages_sent += 1
    db.session.commit()
    emit("new_message", {"username": user.username, "content": message.content, "room_id": room_id}, room=str(room_id))

@app.route("/messages_history", methods=["GET"])
def get_messages():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify(message="User not logged in"), 400
    room_id = request.args.get("room_id")
    messages = Messages.query.filter_by(room_id=room_id).all()
    return jsonify(messages=[{"username": message.user.username, "content": message.content} for message in messages if message.user is not None])

@app.route("/rooms")
def get_rooms():
    rooms = Room.query.all()
    return jsonify([{"id": r.id, "name": r.name} for r in rooms])

@socketio.on("join_room")
def handle_join_room(data):
    room_id = data["room_id"]
    password = data.get("password", "")
    user_id = session.get("user_id")
    if not user_id:
        emit("error", {"message": "Not logged in"})
        return
    user = User.query.get(user_id)
    room = Room.query.get(room_id)
    if not room:
        emit("error", {"message": "Room not found"})
        return

    if user.is_admin:
        join_room(str(room_id))
        if room not in user.rooms:
            user.rooms.append(room)
            user.rooms_joined = len(user.rooms)
            db.session.commit()
        emit("join_success", {"room_id": room_id, "room_name": room.name})
        return

    if room in user.rooms:
        join_room(str(room_id))
        emit("join_success", {"room_id": room_id, "room_name": room.name})
        return

    if not check_password_hash(room.password_hash, password):
        emit("error", {"message": "Invalid password"})
        return

    join_room(str(room_id))
    user.rooms.append(room)
    user.rooms_joined = len(user.rooms)
    db.session.commit()
    emit("join_success", {"room_id": room_id, "room_name": room.name})

@socketio.on("leave_room")
def handle_leave_room(data):
    room_id = data["room_id"]
    user_id = session.get("user_id")
    if user_id is None:
        emit("error", {"message": "User not logged in"})
        return
    user = User.query.get(user_id)
    room = Room.query.get(room_id)
    if not room:
        emit("error", {"message": "Room not found"})
        return
    leave_room(str(room_id))
    emit("user_left", {"username": user.username}, room=str(room_id))

@app.route("/create/rooms", methods=["POST"])
def create_room():
    data = request.get_json()
    if data is None:
        return jsonify(message="No data provided"), 400
    room_name = data.get("name")
    password = data.get("password")
    if room_name is None or len(room_name) > 30 or len(room_name) < 3:
        return jsonify(message="Room name must be between 3 and 30 characters"), 400
    if password is None or len(password) < 3 or len(password) > 30:
        return jsonify(message="Password must be between 3 and 30 characters"), 400
    existing_room = Room.query.filter_by(name=room_name).first()
    if existing_room:
        return jsonify(message="A room with that name already exists"), 400
    hashed_password = generate_password_hash(password)
    created_at = datetime.now()
    try:
        room = Room(name=room_name, password_hash=hashed_password, created_at=created_at)
        db.session.add(room)
        db.session.commit()
        return jsonify(message="Room created successfully"), 200
    except Exception as e:
        db.session.rollback()
        return jsonify(message=f"Database error: {str(e)}"), 500

@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.all()
    return jsonify([{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "is_admin": u.is_admin,
        "messages_sent": u.messages_sent,
        "rooms_joined": len(u.rooms)
    } for u in users])

# ------------------------- Run -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
