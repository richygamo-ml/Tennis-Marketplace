import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import hashlib
import stripe
import os

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

from dotenv import load_dotenv
load_dotenv()

DB = "tennis_app.db"

# ---------------- DB INIT ----------------
def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS coaches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            location TEXT,
            bio TEXT,
            photo TEXT,
            user_id INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS lesson_types(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER,
            type TEXT,
            duration INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS lesson_pricing(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_type_id INTEGER,
            group_size INTEGER,
            price INTEGER
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS availability(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER,
            date TEXT,
            start_time TEXT,
            end_time TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS bookings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER,
            lesson_type_id INTEGER,
            student_name TEXT,
            lesson_date TEXT,
            lesson_time TEXT,
            group_size INTEGER
        )
        """)

init_db()



# ---------------- HELPERS ----------------
def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def query(sql, params=()):
    with sqlite3.connect(DB) as conn:
        return pd.read_sql(sql, conn, params=params)

def execute(sql, params=()):
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()

        

# ---------------- SLOTS ----------------
def generate_slots(start, end, duration):
    start = datetime.strptime(start, "%H:%M")
    end = datetime.strptime(end, "%H:%M")

    slots = []
    while start + timedelta(minutes=duration) <= end:
        slots.append(start.strftime("%H:%M"))
        start += timedelta(minutes=duration)

    return slots

def available_slots(coach_id, date, duration):
    blocks = query(
        "SELECT start_time,end_time FROM availability WHERE coach_id=? AND date=?",
        (coach_id, date)
    )

    if blocks.empty:
        return []

    all_slots = []

    for _, row in blocks.iterrows():
        slots = generate_slots(row["start_time"], row["end_time"], duration)
        all_slots.extend(slots)

    booked = query(
        "SELECT lesson_time FROM bookings WHERE coach_id=? AND lesson_date=?",
        (coach_id, date)
    )

    booked_list = booked["lesson_time"].tolist()

    return [s for s in all_slots if s not in booked_list]
    

# -------------- COUNT BOOKINGS PER SLOT ---------------
def get_slot_bookings(coach_id, lesson_type_id, date, time):
    df = query("""
    SELECT SUM(group_size) as total
    FROM bookings
    WHERE coach_id=? AND lesson_type_id=? AND lesson_date=? AND lesson_time=?
    """, (coach_id, lesson_type_id, date, time))

    if df.iloc[0]["total"] is None:
        return 0

    return int(df.iloc[0]["total"])
    

# ---------------- UI STYLE ----------------
st.set_page_config(page_title="Tennis Marketplace", layout="wide")

st.markdown("""
<style>
.card {
    padding: 1rem;
    border-radius: 12px;
    background: white;
    box-shadow: 0 4px 10px rgba(0,0,0,0.05);
    margin-bottom: 1rem;
}
</style>
""", unsafe_allow_html=True)

st.title("🎾 Tennis Marketplace")
st.info("Demo: Login as coach or client to explore")



# ---------------- AUTH GATE ----------------
if "user" not in st.session_state:
    menu = st.sidebar.selectbox("Menu", ["Login", "Signup"])
else:
    menu = st.sidebar.selectbox("Menu", [
        "Dashboard",
        "My Coach Profile",
        "Manage My Lessons",
        "Set My Schedule",
        "Find Your Coach 🎾",
        "Book a Session 📅",
        "Logout"
    ])



# ---------------- SIGNUP ----------------
if menu == "Signup":

    st.header("Create Account")

    username = st.text_input("Username")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    role = st.selectbox("Role", ["coach", "client"])

    if st.button("Signup"):

        if not username or not email or not password:
            st.error("Fill all fields")
        else:
            try:
                execute("""
                INSERT INTO users (username,email,password,role)
                VALUES (?,?,?,?)
                """, (
                    username,
                    email.lower(),
                    hash_password(password),
                    role
                ))

                st.success("Account created")
            except:
                st.error("User already exists")

                

# ---------------- LOGIN ----------------
elif menu == "Login":
    st.header("Login")

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        user = query(
            "SELECT * FROM users WHERE email=?",
            (email.lower(),)
        )

        if not user.empty:
            stored_pw = user.iloc[0]["password"]

            if stored_pw == hash_password(password):
                st.session_state["user"] = user.iloc[0].to_dict()
                st.success("Logged in")
                st.rerun()
            else:
                st.error("Wrong password")
        else:
            st.error("User not found")

            

# ---------------- LOGOUT ----------------
elif menu == "Logout":
    st.session_state.clear()
    st.success("Logged out")
    st.rerun()


    

# ---------------- DASHBOARD ----------------
elif menu == "Dashboard":
    st.header(f"Welcome {st.session_state['user']['username']} 👋")


# ------ HELPER FUNCTION -------    

def save_image(file):
    if file is None:
        return None

    os.makedirs("uploads", exist_ok=True)

    path = os.path.join("uploads", file.name)

    with open(path, "wb") as f:
        f.write(file.getbuffer())

    return path


# ---------------- COACH PROFILE ----------------
if menu == "My Coach Profile":

    if st.session_state["user"]["role"] != "coach":
        st.error("Only coaches")
        st.stop()

    user_id = st.session_state["user"]["id"]

    existing_df = query("SELECT * FROM coaches WHERE user_id=?", (user_id,))

    # PREFILL VALUES
    if not existing_df.empty:
        existing = existing_df.iloc[0]

        default_name = existing["name"]
        default_location = existing["location"]
        default_bio = existing["bio"]
        default_photo = existing["photo"]
    else:
        existing = None
        default_name = ""
        default_location = ""
        default_bio = ""
        default_photo = ""

    # INPUTS
    name = st.text_input("Name", value=default_name)
    location = st.text_input("Location", value=default_location)
    bio = st.text_area("Bio", value=default_bio)
    photo_file = st.file_uploader("Upload Profile Picture", type=["png", "jpg", "jpeg"])

    # -------- SAVE PROFILE --------
    if st.button("Save Profile"):

        photo_path = save_image(photo_file) if photo_file else default_photo

        if existing is not None:
            execute("""
            UPDATE coaches
            SET name=?, location=?, bio=?, photo=?
            WHERE user_id=?
            """, (name, location, bio, photo_path, user_id))
        else:
            execute("""
            INSERT INTO coaches(name,location,bio,photo,user_id)
            VALUES (?,?,?,?,?)
            """, (name, location, bio, photo_path, user_id))

        st.success("Profile saved!")
        st.rerun()

        

# ---------------- LESSONS ----------------
elif menu == "Manage My Lessons":

    user_id = st.session_state["user"]["id"]
    coach = query("SELECT * FROM coaches WHERE user_id=?", (user_id,))

    if coach.empty:
        st.warning("Create profile first")
        st.stop()

    coach_id = coach.iloc[0]["id"]

    st.header("Manage Lesson Types")


    # -------- CREATE LESSON TYPE --------
    lesson_type = st.selectbox("Lesson Type", ["private", "group"])
    duration = st.number_input("Duration (minutes)", 60)

    if st.button("Create Lesson Type"):
        execute("""
        INSERT INTO lesson_types (coach_id,type,duration)
        VALUES (?,?,?)
        """, (coach_id, lesson_type, duration))

        st.success(f"{lesson_type.capitalize()} lesson created")
        

    # -------- SELECT LESSON --------
    lessons = query("SELECT * FROM lesson_types WHERE coach_id=?", (coach_id,))

    if not lessons.empty:

        lesson_display = lessons.apply(
            lambda x: f"{x['type']} ({x['duration']} min)", axis=1
        )

        selected = st.selectbox("Select Lesson Type", lesson_display)

        lesson_id = lessons.iloc[lesson_display.tolist().index(selected)]["id"]
        lesson_type = lessons.iloc[lesson_display.tolist().index(selected)]["type"]

        st.divider()
        st.subheader("💰 Pricing (USD)")


        # -------- PRICING INPUT --------
        if lesson_type == "group":
            group_size = st.number_input("Number of Players", 2, 10)
            price = st.number_input("Price per person ($)", 20)
        else:
            group_size = 1
            price = st.number_input("Price ($)", 50)

        if st.button("Add Pricing"):
            execute("""
            INSERT INTO lesson_pricing (lesson_type_id,group_size,price)
            VALUES (?,?,?)
            """, (lesson_id, group_size, price))

            st.success("Pricing added")
            

        # -------- SHOW PRICING --------
        pricing = query(
            "SELECT * FROM lesson_pricing WHERE lesson_type_id=?",
            (lesson_id,)
        )

        if not pricing.empty:
            for _, p in pricing.iterrows():
                if lesson_type == "group":
                    st.write(f"{p['group_size']} players → ${p['price']} per person")
                else:
                    st.write(f"Private lesson → ${p['price']}")

        

# ---------------- AVAILABILITY ----------------
elif menu == "Set My Schedule":

    user_id = st.session_state["user"]["id"]
    coach = query("SELECT * FROM coaches WHERE user_id=?", (user_id,))
    if coach.empty:
        st.stop()

    coach_id = coach.iloc[0]["id"]

    date = st.date_input("Date")
    start = st.text_input("Start", "15:00")
    end = st.text_input("End", "16:00")

    if st.button("Add Block"):
        execute("""
        INSERT INTO availability (coach_id,date,start_time,end_time)
        VALUES (?,?,?,?)
        """, (coach_id, str(date), start, end))
        st.success("Added")

    blocks = query("SELECT * FROM availability WHERE coach_id=?", (coach_id,))

    for _, b in blocks.iterrows():
        col1, col2 = st.columns([3,1])
        col1.write(f"{b['date']} | {b['start_time']} - {b['end_time']}")
        if col2.button("❌", key=f"del_{b['id']}"):
            execute("DELETE FROM availability WHERE id=?", (b["id"],))
            st.rerun()



# ---------------- BROWSE ----------------
elif menu == "Find Your Coach 🎾":

    coaches = query("SELECT * FROM coaches")

    if coaches.empty:
        st.warning("No coaches yet")

    for _, c in coaches.iterrows():
        st.markdown('<div class="card">', unsafe_allow_html=True)

        col1, col2 = st.columns([1,3])

        with col1:
            if c["photo"]:
                st.image(c["photo"], width=100)
            else:
                st.image("https://via.placeholder.com/100")

        with col2:
            st.subheader(c["name"])
            st.write(c["location"])
            st.write(c["bio"])

        st.markdown('</div>', unsafe_allow_html=True)
        

# ----------- Instead of just listing coaches, user clicks, sees details ----------
    if st.button(f"View {c['name']}", key=f"view_{c['id']}"):
        st.session_state["selected_coach"] = c["id"]
        st.session_state["page"] = "coach_profile"
        st.rerun()

    elif st.session_state.get("page") == "coach_profile":
        coach_id = st.session_state["selected_coach"]
        coach = query("SELECT * FROM coaches WHERE id=?", (coach_id,)).iloc[0]
        st.header(coach["name"])
        
        if coach["photo"]:
            st.image(coach["photo"], width=200)
            st.write(f"📍 {coach['location']}")
            st.write(coach["bio"])
            st.divider()

    # -------- LESSONS --------
        lessons = query("SELECT * FROM lesson_types WHERE coach_id=?", (coach_id,))
        
        for _, lesson in lessons.iterrows():
            st.subheader(f"{lesson['type'].capitalize()} Lesson ({lesson['duration']} min)")
            
            pricing = query(
            "SELECT * FROM lesson_pricing WHERE lesson_type_id=?",
            (lesson["id"],)
            )
            
            for _, p in pricing.iterrows():
                if lesson["type"] == "group":
                    st.write(f"{p['group_size']} players → ${p['price']} per person")
                else:
                    st.write(f"Private → ${p['price']}")
                    
        if st.button("⬅ Back"):
            st.session_state["page"] = None
            st.rerun()

        
# --------- AI MATCHING UI ------------
elif menu == "Find Best Coach 🤖":

    st.header("AI Coach Finder")

    query_text = st.text_input("What are you looking for?")

    if st.button("Find"):

        results = recommend_coaches(query_text)

        if results is not None:

            for _, c in results.head(3).iterrows():
                st.subheader(c["name"])
                st.write(c["location"])
                st.write(c["bio"])
                st.divider()


                
# ---------------- BOOK ----------------
elif menu == "Book a Session 📅":

    if st.session_state["user"]["role"] != "client":
        st.warning("Clients only")
        st.stop()

    coaches = query("SELECT * FROM coaches")

    if coaches.empty:
        st.warning("No coaches available")
        st.stop()

    coach_name = st.selectbox("Coach", coaches["name"])
    coach_id = coaches[coaches["name"] == coach_name]["id"].iloc[0]

    lessons = query("SELECT * FROM lesson_types WHERE coach_id=?", (coach_id,))

    if lessons.empty:
        st.warning("No lessons available")
        st.stop()

    lesson_display = lessons.apply(
        lambda x: f"{x['type']} ({x['duration']} min)", axis=1
    )

    selected = st.selectbox("Lesson Type", lesson_display)

    lesson_row = lessons.iloc[lesson_display.tolist().index(selected)]
    lesson_id = lesson_row["id"]
    

    # ---------- DEFINE PRICING -------------
    pricing = query(
    "SELECT * FROM lesson_pricing WHERE lesson_type_id=?",
    (lesson["id"],)
    )
    
    options = []
    mapping = {}
    
    for _, p in pricing.iterrows():
        if lesson["type"] == "group":
            label = f"{p['group_size']} players - ${p['price']} per person"
        else:
            label = f"Private - ${p['price']}"
            
        options.append(label)

    # store BOTH group size AND price
    mapping[label] = {
        "group_size": p["group_size"],
        "price": p["price"]
    }
    
    selected_option = st.selectbox("Choose Option", options)
    selected_data = mapping[selected_option]
    selected_group_size = selected_data["group_size"]
    price = selected_data["price"]


    # Checkout
    session = stripe.checkout.Session.create(
    payment_method_types=["card"],
    line_items=[{
        "price_data": {
            "currency": "usd",
            "product_data": {
                "name": "Tennis Lesson"
            },
            "unit_amount": int(price * 100)
        },
        "quantity": 1
    }],
    mode="payment",
    success_url="http://localhost:8501",
    cancel_url="http://localhost:8501"
    )
    
    st.markdown(f"[Pay Now]({session.url})")
    

    # ---------------- DATE ----------------
    date = st.date_input("Date")

    slots = available_slots(coach_id, str(date), int(lesson_row["duration"]))

    if not slots:
        st.warning("No available slots")
        st.stop()
        

    # ---------------- BOOKING ----------------
    for s in slots:

        current_booked = get_slot_bookings(
            coach_id,
            lesson_id,
            str(date),
            s
        )

        max_capacity = selected_group_size
        spots_left = max_capacity - current_booked

        if spots_left <= 0:
            st.write(f"{s} ❌ Full")
            continue

        if st.button(f"{s} ({spots_left} spots left)", key=f"{date}_{s}"):

            if selected_group_size > spots_left:
                st.error("Not enough spots available")
            else:
                execute("""
                INSERT INTO bookings
                (coach_id,lesson_type_id,student_name,lesson_date,lesson_time,group_size)
                VALUES (?,?,?,?,?,?)
                """, (
                    coach_id,
                    lesson_id,
                    st.session_state["user"]["email"],
                    str(date),
                    s,
                    selected_group_size
                ))

                st.success(f"✅ Booked {selected_group_size} spot(s) at {s}")
                st.balloons()
                
                

# ---------------- AI MATCHING --------------
def recommend_coaches(user_query):

    coaches = query("SELECT * FROM coaches")

    if coaches.empty:
        return None

    # simple scoring (upgrade later with embeddings)
    coaches["score"] = 0

    for i, row in coaches.iterrows():

        score = 0

        if "beginner" in user_query.lower():
            score += 2

        if "cheap" in user_query.lower() or "$" in user_query:
            score += 2

        if row["location"] and row["location"].lower() in user_query.lower():
            score += 3

        coaches.at[i, "score"] = score

    return coaches.sort_values("score", ascending=False)


