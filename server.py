from flask import Flask
import os
from flask import Flask, flash, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS
import subprocess
from pymongo import MongoClient
import json
import shortuuid

# grammar model
from happytransformer import HappyTextToText, TTSettings
happy_tt = HappyTextToText("T5", "vennify/t5-base-grammar-correction")
args = TTSettings(num_beams=5, min_length=1)

# transcription -> audio to text
import whisper
whisperModel = whisper.load_model("base")


app = Flask(__name__)
UPLOAD_FOLDER = './uploads'
ALLOWED_EXTENSIONS = {"webm" , "mp4"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
CORS(app)

# mongo db config
client = MongoClient("mongodb://localhost:27017/")
db = client["speechinator"]
take = db["take"]


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def home():
    return "Hello, World!"

@app.route("/processvideo", methods = ["POST"])
def processVideo():
    if 'file' not in request.files:
        return jsonify({"message" : "no video file found" , "code" : "error"})
    file = request.files['file']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'],"video", filename))  
        # clip = VideoFileClip(file)
        # clip.audio.write_audiofile(f"uploads/audio/{filename}.mp3")
        subprocess.call(["ffmpeg", "-y", "-i", "./uploads/video/"+filename, f"./uploads/audio/{filename}.mp3"], 
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT)
                    
        data = json.loads(request.form["data"])
        print(data)
        s = shortuuid.encode(u)
        short = s[:5]
        take.insert_one(
            {"filename": filename, "script": data["script"], "scriptname": data["scriptname"], "practiceid": short})

        return jsonify({"message": "Saved" , "code": "success" })


@app.route("/correct-grammar", methods= ["POST"])
def correctGrammar():
    text = request.get_json()["text"]
    print(text)
    res = happy_tt.generate_text(text, args=args)
    print(res)
    return jsonify({ "corrected" : res.text })


@app.route("/transcribe", methods= ["POST"])
def transcribe():
    filename = request.get_json()["filename"]
    # print(text)

    result  = whisperModel.transcribe("uploads\\audio\\"+ filename)
    f = open("uploads\\transcription\\" + filename + ".txt" , "x")
    f.write(result["text"])
    f.close()
    return jsonify({ "transcribe" : result["text"] })

if __name__ == "__main__":
    app.run(debug=True)