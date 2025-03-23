from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, url_for, session
import sqlite3
import base64
from datetime import datetime
import face_recognition
import numpy as np
import cv2
import os
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import pandas as pd
from flask_socketio import SocketIO, emit
from flask_mail import Mail, Message
load_dotenv()
connected_users = {}
app = Flask(__name__)
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT'))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')



mail = Mail(app)
app.secret_key = os.getenv('SECRET_KEY')
socketio = SocketIO(app, cors_allowed_origins="*")
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/student_login')
def student_login():
    return render_template('student_login.html')

@app.route('/student_register')
def student_register():
    return render_template('student_register.html')

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    # Check if the file is from "invigilation" or "uploads"
    if filename.startswith("invigilation/"):
        return send_from_directory('invigilation', filename.replace("invigilation/", ""))
    return send_from_directory('uploads', filename)

@app.route('/admin')
def admin():
    return render_template('Admin.html')

@app.route('/admin_login', methods=['POST'])
def admin_login():
    data = request.json
    admin_username = os.getenv('ADMIN_USERNAME')
    admin_password = os.getenv('ADMIN_PASSWORD')

    if data['username'] == admin_username and data['password'] == admin_password:
        return jsonify({"status": "success", "message": "Login successful!"})
    else:
        return jsonify({"status": "error", "message": "Incorrect username or password!"})

@app.route('/admin_logout', methods=['POST'])
def admin_logout():
    # Logic for admin logout (e.g., clearing session data)
    return jsonify({"status": "success", "message": "Logout successful!"})

@app.route('/api/admin/students', methods=['GET'])
def get_admin_students():
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    
    cursor.execute("SELECT Username, Name, Email, Photograph, Access FROM Student_Details")
    students = cursor.fetchall()
    
    conn.close()

    student_list = [
        {
            "username": student[0],
            "name": student[1],
            "email": student[2],
            "photo": student[3],
            "access": student[4]
        }
        for student in students
    ]

    return jsonify(student_list)

@app.route('/api/admin/students/<username>/access', methods=['POST'])
def update_student_access(username):
    data = request.json
    new_access = data['access']

    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    
    cursor.execute("UPDATE Student_Details SET Access=? WHERE Username=?", (new_access, username))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Access updated successfully!"})

@app.route('/api/admin/students/<username>', methods=['DELETE'])
def delete_student(username):
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM Student_Details WHERE Username=?", (username,))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Student deleted successfully!"})

@app.route('/api/admin/students/<username>/exam_status', methods=['GET'])
def get_exam_status(username):
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM exam_result WHERE username=?", (username,))
    result = cursor.fetchone()
    conn.close()

    exam_status = "Taken" if result[0] > 0 else "Not Taken"
    return jsonify({"exam_status": exam_status})

@app.route('/api/admin/students/<username>/exam_result', methods=['DELETE'])
def delete_exam_result(username):
    data = request.json
    email = data['email']

    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    
    # Delete from exam_result table
    cursor.execute("DELETE FROM exam_result WHERE username=? AND email=?", (username, email))
    
    # Fetch video path from exam_invigilation table
    cursor.execute("SELECT video_path FROM exam_invigilation WHERE username=? AND email=?", (username, email))
    video_path = cursor.fetchone()
    
    # Delete from exam_invigilation table
    cursor.execute("DELETE FROM exam_invigilation WHERE username=? AND email=?", (username, email))
    
    conn.commit()
    conn.close()

    # Delete the video file if it exists
    if video_path and os.path.exists(video_path[0]):
        os.remove(video_path[0])

    return jsonify({"status": "success", "message": "Exam result and invigilation record deleted successfully!"})

# Database Initialization
def init_db():
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS Student_Details (
                        Username TEXT PRIMARY KEY,
                        Name TEXT,
                        Date_of_Birth TEXT,  
                        Father_Name TEXT,  
                        Email TEXT,
                        Photograph TEXT,
                        Address TEXT,
                        Password TEXT,
                        Date_of_creation TEXT DEFAULT CURRENT_TIMESTAMP,
                        Access TEXT DEFAULT 'DISABLED')''')
    conn.commit()
    conn.close()

# Call the function to initialize the database
init_db()

@app.route('/register', methods=['POST'])
def register():
    data = request.json

    try:
        # Establish connection with timeout and WAL mode
        conn = sqlite3.connect('exam_db.sqlite', timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")  # Enable WAL mode
        cursor = conn.cursor()

        # Check if the username or email already exists
        cursor.execute("SELECT * FROM Student_Details WHERE Username=? OR Email=?", 
                       (data['username'], data['email']))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "message": "Profile already exists!"})

        # Save the photo to the uploads folder
        if not os.path.exists('uploads'):
            os.makedirs('uploads')
        
        photo_path = f"uploads/{data['username']}.png"
        with open(photo_path, "wb") as fh:
            fh.write(base64.b64decode(data['photo'].split(",")[1]))

        # Insert new student record
        cursor.execute("""
            INSERT INTO Student_Details (Username, Name, Date_of_Birth, Father_Name, Email, Photograph, Address, Password) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['username'], 
            data['fullname'], 
            data['dob'],          # Date of Birth added
            data['Father_Name'],  # Parent Name added
            data['email'], 
            photo_path, 
            data['address'], 
            data['password']
        ))

        conn.commit()
        return jsonify({"status": "success", "message": "Your profile has been successfully created!"})
    
    except sqlite3.OperationalError as e:
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"})

    finally:
        cursor.close()  # Ensure the cursor is closed
        conn.close()  # Ensure the connection is closed

@app.route('/api/students', methods=['GET'])
def get_students():
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    
    cursor.execute("SELECT Username, Name, Date_of_Birth, Father_Name, Email, Address FROM Student_Details")
    students = cursor.fetchall()
    
    conn.close()

    student_list = [
        {
            "username": student[0],
            "name": student[1],
            "dob": student[2],
            "Father_Name": student[3],
            "email": student[4],
            "address": student[5]
        }
        for student in students
    ]

    return jsonify(student_list)

@app.route('/face_login', methods=['POST'])
def face_login():
    try:
        data = request.json
        captured_image_data = base64.b64decode(data['image'].split(",")[1])  # Remove "data:image/jpeg;base64,"

        # Convert image to OpenCV format
        nparr = np.frombuffer(captured_image_data, np.uint8)
        captured_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        captured_face_encodings = face_recognition.face_encodings(captured_image)

        if not captured_face_encodings:
            return jsonify({"status": "error", "message": "No face detected!"})

        captured_encoding = captured_face_encodings[0]

        # Connect to database and fetch stored images
        conn = sqlite3.connect('exam_db.sqlite')
        cursor = conn.cursor()
        cursor.execute("SELECT Username, Photograph FROM Student_Details")
        users = cursor.fetchall()

        for username, photo_path in users:
            if not photo_path:
                continue

            stored_image = cv2.imread(photo_path)
            stored_face_encodings = face_recognition.face_encodings(stored_image)
            if stored_face_encodings and face_recognition.compare_faces([stored_face_encodings[0]], captured_encoding)[0]:
                cursor.execute("SELECT * FROM Student_Details WHERE Username=?", (username,))
                user_profile = cursor.fetchone()
                conn.close()

                # Store user profile in session
                session['username'] = user_profile[0]
                session['name'] = user_profile[1]
                session['dob'] = user_profile[2]
                session['Father_Name'] = user_profile[3]
                session['email'] = user_profile[4]
                session['address'] = user_profile[6]
                session['photo'] = user_profile[5]

                return jsonify({
                    "status": "success", 
                    "message": f"Profile found! Welcome {username}!",
                    "profile": {
                        "username": user_profile[0],
                        "name": user_profile[1],
                        "dob": user_profile[2],
                        "Father_Name": user_profile[3],
                        "email": user_profile[4],
                        "address": user_profile[6],
                        "access": user_profile[9],
                        "photo": user_profile[5]
                    }
                })

        conn.close()
        return jsonify({"status": "error", "message": "Profile not found!"})

    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"})

@app.route('/login', methods=['POST'])
def login():
    data = request.json

    try:
        # Establish connection with timeout and WAL mode
        conn = sqlite3.connect('exam_db.sqlite', timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")  # Enable WAL mode
        cursor = conn.cursor()

        # Check if the username and password match
        cursor.execute("SELECT * FROM Student_Details WHERE Username=? AND Password=?", 
                       (data['username'], data['password']))
        user_profile = cursor.fetchone()

        if user_profile:
            if user_profile[9] == "DISABLED":
                return jsonify({"status": "error", "message": "Admin has not yet approved your profile."})
            else:
                # Store user profile in session
                session['username'] = user_profile[0]
                session['name'] = user_profile[1]
                session['dob'] = user_profile[2]
                session['Father_Name'] = user_profile[3]
                session['email'] = user_profile[4]
                session['address'] = user_profile[6]
                session['photo'] = user_profile[5]
                return jsonify({
                    "status": "success", 
                    "message": f"Profile found! Welcome {user_profile[1]}!",
                    "profile": {
                        "username": user_profile[0],
                        "name": user_profile[1],
                        "dob": user_profile[2],
                        "Father_Name": user_profile[3],
                        "email": user_profile[4],
                        "address": user_profile[6],
                        "access": user_profile[9],
                        "photo": user_profile[5]
                    }
                })
        else:
            return jsonify({"status": "error", "message": "Profile does not exist!"})

    except sqlite3.OperationalError as e:
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"})

    finally:
        cursor.close()  # Ensure the cursor is closed
        conn.close()  # Ensure the connection is closed

@app.route('/upload_exam', methods=['POST'])
def upload_exam():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"})
    
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        filename = secure_filename(file.filename)
        file_path = os.path.join('uploads', filename)
        file.save(file_path)

        try:
            # Read the Excel file
            df = pd.read_excel(file_path)
            num_records = len(df)

            # Connect to the database
            conn = sqlite3.connect('exam_db.sqlite')
            cursor = conn.cursor()

            # Create the exam table if it doesn't exist
            cursor.execute('''CREATE TABLE IF NOT EXISTS exam (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                Question TEXT,
                                Option_a TEXT,
                                Option_b TEXT,
                                Option_c TEXT,
                                Option_d TEXT,
                                correct_answer TEXT,
                                explanation TEXT)''')

            # Insert the data into the exam table
            for index, row in df.iterrows():
                cursor.execute('''INSERT INTO exam (Question, Option_a, Option_b, Option_c, Option_d, correct_answer, explanation)
                                  VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                               (row[0], row[1], row[2], row[3], row[4], row[5], row[6]))

            # Create the exam_result table with dynamic columns
            columns = ['name TEXT', 'username TEXT', 'email TEXT']
            for i in range(1, num_records + 1):
                columns.append(f'question_{i} TEXT')
            columns_str = ', '.join(columns)
            cursor.execute(f'CREATE TABLE IF NOT EXISTS exam_result ({columns_str})')

            conn.commit()
            conn.close()

            return jsonify({"status": "success", "message": "File uploaded and data inserted successfully!"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"Error processing file: {str(e)}"})
    else:
        return jsonify({"status": "error", "message": "Invalid file type. Please upload an Excel file."})

@app.route('/delete_exam_records', methods=['DELETE'])
def delete_exam_records():
    try:

        invigilation_folder = "invigilation"

        # Delete all files inside the invigilation folder
        if os.path.exists(invigilation_folder):
            for file in os.listdir(invigilation_folder):
                file_path = os.path.join(invigilation_folder, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):  # If there are subdirectories, remove them as well
                    shutil.rmtree(file_path)

        invigilation_folder = "uploads"

        # Delete all files inside the invigilation folder
        if os.path.exists(invigilation_folder):
            for file in os.listdir(invigilation_folder):
                file_path = os.path.join(invigilation_folder, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):  # If there are subdirectories, remove them as well
                    shutil.rmtree(file_path)
        conn = sqlite3.connect('exam_db.sqlite')
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS exam")
        cursor.execute("DROP TABLE IF EXISTS exam_result")
        cursor.execute("DROP TABLE IF EXISTS Student_reminder")
        cursor.execute("DROP TABLE IF EXISTS exam_invigilation")
        cursor.execute("DROP TABLE IF EXISTS Student_details")
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "All exam records and exam_result table deleted successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error deleting records: {str(e)}"})

@app.route('/take_exam')
def take_exam():
    user_profile = {
        "username": session.get('username'),
        "name": session.get('name'),
        "dob": session.get('dob'),
        "Father_Name": session.get('Father_Name'),
        "email": session.get('email'),
        "address": session.get('address'),
        "photo": session.get('photo')
    }
    return render_template('take_exam.html', profile=user_profile)

@app.route('/exam_paper')
def exam_paper():
    user_profile = {
        "username": session.get('username'),
        "name": session.get('name'),
        "dob": session.get('dob'),
        "Father_Name": session.get('Father_Name'),
        "email": session.get('email'),
        "address": session.get('address'),
        "photo": session.get('photo')
    }

    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    cursor.execute("SELECT id, Question, Option_a, Option_b, Option_c, Option_d FROM exam")
    questions = cursor.fetchall()
    conn.close()

    return render_template('exam_paper.html', profile=user_profile, questions=questions)

@app.route('/instructions_pdf')
def instructions_pdf():
    return send_from_directory(directory='.', path='Instructions.pdf')

@app.route('/submit_exam', methods=['POST'])
def submit_exam():
    data = request.form.to_dict()
    username = session.get('username')
    name = session.get('name')
    email = session.get('email')

    # Prepare data for insertion
    exam_result = {
        'name': name,
        'username': username,
        'email': email
    }
    for key, value in data.items():
        exam_result[key] = value

    columns = ', '.join(exam_result.keys())
    placeholders = ', '.join(['?'] * len(exam_result))
    values = list(exam_result.values())

    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    cursor.execute(f"INSERT INTO exam_result ({columns}) VALUES ({placeholders})", values)
    cursor.execute("UPDATE Student_Details SET Access='DISABLED' WHERE Username=?", (username,))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Thank you for submitting the exam!"})



@socketio.on('connect', namespace='/ws/video')
def video_connect():
    print("Student connected for video recording")
    session_id = request.sid  # Unique session ID for each connection
    connected_users[session_id] = {"username": session.get("username", "unknown"),
                                   "email": session.get("email", "unknown")}
    emit("status", {"message": "Connected successfully"})

@socketio.on('disconnect', namespace='/ws/video')
def video_disconnect():
    print("Student disconnected, stopping recording")
    session_id = request.sid
    connected_users.pop(session_id, None)

@socketio.on('video_chunk', namespace='/ws/video')
def handle_video_chunk(video_chunk):
    session_id = request.sid
    user_info = connected_users.get(session_id, {"username": "unknown", "email": "unknown"})
    
    username = user_info["username"]
    email = user_info["email"]
    
    video_filename = f"{username}_{email}.mp4"
    video_folder = "invigilation" 
    video_path = os.path.join(video_folder, video_filename)
    # If chunk is base64 encoded, decode it
    if isinstance(video_chunk, str):
        try:
            video_chunk = base64.b64decode(video_chunk)
        except Exception as e:
            print(f"Error decoding base64 chunk: {e}")

    # Append to the video file
    with open(video_path, "ab") as f:
        f.write(video_chunk)

    print(f"Saved chunk for {video_filename}")

@app.route('/save_invigilation_video', methods=['POST'])
def save_invigilation_video():
    if 'video' not in request.files:
        return jsonify({"status": "error", "message": "No video part"})

    video = request.files['video']
    username = session.get('username')
    email = session.get('email')
    name = session.get('name')

    if not os.path.exists('invigilation'):
        os.makedirs('invigilation')

    video_filename = f"{username}_{email}.mp4"
    video_path = os.path.join('invigilation', video_filename)
    video.save(video_path)

    # Store in SQLite Database
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS exam_invigilation (
                        name TEXT,
                        username TEXT,
                        email TEXT,
                        video_path TEXT)''')
    cursor.execute("INSERT INTO exam_invigilation (name, username, email, video_path) VALUES (?, ?, ?, ?)",
                   (name, username, email, video_path))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "Video saved successfully!"})


@app.route('/get_invigilation_data', methods=['GET'])
def get_invigilation_data():
    conn = sqlite3.connect('exam_db.sqlite')
    cursor = conn.cursor()
    cursor.execute("SELECT name, username, email, video_path FROM exam_invigilation")
    records = cursor.fetchall()
    conn.close()

    # Convert to JSON format
    data = []
    for row in records:
        data.append({
            "name": row[0],
            "username": row[1],
            "email": row[2],
            "video_path": row[3]  # Path to video file
        })

    return jsonify(data)


@app.route('/get_student_status')
def get_student_status():
    connection = sqlite3.connect("exam_db.sqlite")
    cursor = connection.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Student_reminder (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            name TEXT,
            email TEXT,
            reminder INTEGER DEFAULT 0
        )
    ''')
    connection.commit()
    connection.close()
    connection = sqlite3.connect("exam_db.sqlite")
    cursor = connection.cursor()
    query = '''
    SELECT sd.Name, sd.Username, sd.Email, sd.Photograph, 
           COALESCE(sr.Reminder, 0) AS Reminder
    FROM Student_Details sd
    LEFT JOIN Student_Reminder sr ON sd.Username = sr.Username
    WHERE sd.Username NOT IN (SELECT username FROM exam_result)
    '''
    
    cursor.execute(query)
    students = cursor.fetchall()
    connection.close()
    print('the value of students' , students)

    student_list = []
    for student in students:
        student_list.append({
            "name": student[0],
            "username": student[1],
            "email": student[2],
            "photograph": student[3],  # Assuming this is the image path
            "reminder": int(student[4]) if student[4] is not None else 0  # Ensure integer type
        })
   
    return jsonify(student_list)

@app.route('/send_exam_reminder', methods=['POST'])
def send_exam_reminder():
    data = request.json
    name = data.get('name')
    email = data.get('email')
    username = data.get('username')

    if not name or not email or not username:
        return jsonify({"status": "error", "message": "Missing data"}), 400

    conn = sqlite3.connect("exam_db.sqlite")
    cursor = conn.cursor()

    # Create the Student_reminder table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Student_reminder (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            name TEXT,
            email TEXT,
            reminder INTEGER DEFAULT 0
        )
    ''')
    conn.commit()

    # Check if student already exists in Student_reminder
    cursor.execute("SELECT reminder FROM Student_reminder WHERE username = ?", (username,))
    result = cursor.fetchone()

    if result:
        print('the value of result' , result)
        print('the value of result["reminder"]' , result[0])
        reminder_count = result[0] + 1
        cursor.execute("UPDATE Student_reminder SET reminder = ? WHERE username = ?", (reminder_count, username))
    else:
        cursor.execute("INSERT INTO Student_reminder (username, name, email, reminder) VALUES (?, ?, ?, 1)", 
                       (username, name, email))

    conn.commit()
    conn.close()

    # Sending email logic (assuming you have email configuration)
    from flask_mail import Mail, Message

    mail = Mail(app)
    msg = Message("Exam Reminder",
                  sender="jaingaurav126@gmail.com",
                  recipients=[email])
    msg.body = f"""
Dear {name},

You have not taken the exam yet. Please complete it as soon as possible.

If you have any issues accessing the exam, feel free to reach out to the support team.

Best Regards,  
Exam Department
"""


    try:
        mail.send(msg)
        return jsonify({"status": "success", "message": "Reminder email sent!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/send_bulk_exam_reminders", methods=["POST"])
def send_bulk_exam_reminders():
    try:
        conn = sqlite3.connect("exam_db.sqlite")
        cursor = conn.cursor()

        # Fetch students who haven't been reminded yet (reminder = 0)
        cursor.execute("SELECT name, username, email FROM Student_reminder")
        students = cursor.fetchall()

        if not students:
            return jsonify({"status": "error", "message": "All students have already been reminded."})

        updated_students = []

        for student in students:
            name, username, email = student

            # Prepare the email message
            msg = Message("Exam Reminder",
                          sender="jaingaurav126@gmail.com",
                          recipients=[email])
            msg.body = f"""
Dear {name},

You have not taken the exam yet. Please complete it as soon as possible.

If you have any issues accessing the exam, feel free to reach out to the support team.

Best Regards,  
Exam Department
"""

            try:
                mail.send(msg)  # Send email
                updated_students.append(email)  # Add to list of successful emails
            except Exception as e:
                print(f"Failed to send email to {email}: {e}")

        # Update the reminder count for successfully emailed students
        if updated_students:
            cursor.executemany("UPDATE Student_reminder SET reminder = reminder + 1 WHERE email = ?", 
                               [(email,) for email in updated_students])
            conn.commit()

        conn.close()

        return jsonify({"status": "success", "message": f"Reminders sent to {len(updated_students)} students!"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

        
def ensure_marks_column():
    conn = sqlite3.connect("exam_db.sqlite")
    cursor = conn.cursor()

    # Check if the 'marks' column exists
    cursor.execute("PRAGMA table_info(exam_result)")
    columns = [col[1] for col in cursor.fetchall()]
    print('the value of columns' , columns)
    if "marks" not in columns:
        cursor.execute("ALTER TABLE exam_result ADD COLUMN marks INTEGER DEFAULT NULL")
        conn.commit()

    conn.close()

@app.route("/fetch_exam_results", methods=["GET"])
def fetch_exam_results():
    ensure_marks_column()
    conn = sqlite3.connect("exam_db.sqlite")
    cursor = conn.cursor()

    cursor.execute("SELECT name, username, email, marks FROM exam_result")
    data = cursor.fetchall()
    conn.close()

    # Convert data into a JSON format
    results = [
        {"name": row[0], "username": row[1], "email": row[2], "marks": row[3] if row[3] is not None else "Not Graded"}
        for row in data
    ]

    return jsonify({"exam_results": results})



@app.route("/update_exam_results", methods=["POST"])
def update_exam_results():
    conn = sqlite3.connect("exam_db.sqlite")
    cursor = conn.cursor()

    # Fetch correct answers from the 'exam' table
    cursor.execute("SELECT correct_answer FROM exam")
    correct_answers = [row[0] for row in cursor.fetchall()]  # List of correct answers

    # Fetch all exam results
    cursor.execute("PRAGMA table_info(exam_result)")
    columns = [col[1] for col in cursor.fetchall()]  # Get column names

    question_columns = [col for col in columns if col.startswith("question_")]  # Get only question columns

    cursor.execute("SELECT name, username, email, " + ", ".join(question_columns) + " FROM exam_result")
    results = cursor.fetchall()  # Get all records from exam_result

    for row in results:
        name, username, email, *answers = row  # Extract name, username, email, and responses

        # Compare answers with correct answers
        marks = sum(1 for i, ans in enumerate(answers) if i < len(correct_answers) and ans == correct_answers[i])

        # Update the 'marks' column
        cursor.execute("UPDATE exam_result SET marks = ? WHERE username = ?", (marks, username))

    conn.commit()
    conn.close()

    return jsonify({"message": "Exam results updated successfully"}), 200

@app.route('/send_exam_results', methods=['POST'])
def send_exam_results():
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect("exam_db.sqlite")
        cursor = conn.cursor()

        # Fetch all exam results
        df = pd.read_sql_query("SELECT * FROM exam_result", conn)
        conn.close()

        if df.empty:
            return jsonify({"message": "No exam results found"}), 400

        # Save the Excel file
        excel_filename = "exam_results.xlsx"
        df.to_excel(excel_filename, index=False)

        # Get all unique emails from the `email` column
        email_list = df['email'].unique()

        # Send emails with the Excel attachment
        for email in email_list:
            msg = Message("Exam Results", recipients=[email])
            msg.body = "Dear Student,\n\nPlease find your exam results attached.\n\nBest Regards,\nYour Institution"
            
            with open(excel_filename, "rb") as file:
                msg.attach(excel_filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", file.read())

            mail.send(msg)

        # Cleanup: Remove the temporary file
        os.remove(excel_filename)

        return jsonify({"message": "Exam results sent successfully!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

