from functools import partial
from itertools import groupby
from operator import itemgetter
from happytransformer import HappyTextToText, TTSettings
import re
import uuid
import whisper
from flask import Flask
import os
from flask import Flask, flash, request, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from flask_cors import CORS
import subprocess
from pymongo import MongoClient
import json
import shortuuid
import io
from contextlib import redirect_stdout
import datetime
from flask import send_from_directory
mysp = __import__("my-voice-analysis")


# grammar model
happy_tt = HappyTextToText("T5", "vennify/t5-base-grammar-correction")
args = TTSettings(num_beams=5, min_length=1)

# transcription -> audio to text
whisperModel = whisper.load_model("base")


app = Flask(__name__)
UPLOAD_FOLDER = './uploads'
ALLOWED_EXTENSIONS = {"webm", "mp4"}
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


@app.route("/processvideo", methods=["POST"])
def processVideo():
    if 'file' not in request.files:
        return jsonify({"message": "no video file found", "code": "error"})
    file = request.files['file']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], "video", filename))
        # clip = VideoFileClip(file)
        # clip.audio.write_audiofile(f"uploads/audio/{filename}.mp3")
        subprocess.call(["ffmpeg", "-y", "-i", "./uploads/video/"+filename, f"./uploads/audio/{filename}.wav"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.STDOUT)

        data = json.loads(request.form["data"])
        print(data)
        u=uuid.uuid4()
        s = shortuuid.encode(u)
        short = s[:5]
        result = whisperModel.transcribe("uploads\\audio\\" + filename +".wav")
        take.insert_one(
            {"filename": filename,"createdAt":datetime.datetime.now() ,"script": data["script"], "scriptname": data["scriptname"], "practiceid": short, "transcribed_script": result["text"]})

        return jsonify({"message": "Saved", "code": "success", "practiceid": short})


@app.route("/correct-grammar", methods=["POST"])
def correctGrammar():
    text = request.get_json()["text"]
    print(text)
    res = happy_tt.generate_text(text, args=args)
    print(res)
    return jsonify({"corrected": res.text})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    filename = request.get_json()["filename"]
    # print(text)

    result = whisperModel.transcribe("uploads\\audio\\" + filename)
    f = open("uploads\\transcription\\" + filename + ".txt", "x")
    f.write(result["text"])
    f.close()
    return jsonify({"transcribe": result["text"]})


@app.route("/get-take", methods=["POST"])
def getTake():
    data = request.get_json()
    print(data)
    result = take.find_one({"practiceid": data["practiceid"]})
    sn = result["scriptname"]
    pastdata = {
        "wpm": [],
        "pauses": [],
        "speechpercent": [],
    }
    prev = take.find({"scriptname": sn})
    for p in prev:
        pastdata["wpm"].append(p["analytics"]["wpm"])
        pastdata["pauses"].append(p["analytics"]["pauses"])
        pastdata["speechpercent"].append(p["analytics"]["speechpercent"])
    final = {
        "scriptname": result["scriptname"],
        "script": result["script"],
        "transcribedScript": result["transcribed_script"],
        "analytics": result["analytics"],
        "pastdata": pastdata,
        "vidurl": result["filename"]
    }
    return jsonify({"take": final})


def del_ret(d, key):
    del d[key]
    return d


@app.route("/getalltakes", methods=["GET"])
def getTakes():
    takes = []
    result = take.find({})
    for r in result:
        del r["_id"]
        takes.append(r)

    pop = dict(map(lambda k_v: (k_v[0], tuple(map(partial(del_ret, key="scriptname"), k_v[1]))),
                   groupby(takes, itemgetter("scriptname"))))

    return jsonify({"takes": pop})


@app.route("/analysis", methods=["POST"])
def analysis():
    data = request.get_json()
    practiceid = data["practiceid"]

    result = take.find_one({"practiceid": practiceid})

    fileb = result["filename"]
    print(fileb)
    script = result["script"]
    p = fileb
    c = r"D:\Speechinator-3000\backend\uploads\audio"

    sr = io.StringIO()
    with redirect_stdout(sr):
        mysp.myspsr(p, c)
    speechrate = sr.getvalue()
    speechrate = re.findall("\d+",speechrate)
    speechrate = int(speechrate[0])
    print(speechrate)

    numpause = io.StringIO()
    with redirect_stdout(numpause):
        mysp.mysppaus(p, c)
    pauses = numpause.getvalue()
    print(pauses)
    pauses = re.findall("\d+", pauses)
    pauses = int(pauses[0])

    speakdur = io.StringIO()
    with redirect_stdout(speakdur):
        mysp.myspst(p, c)
    speakingduration = speakdur.getvalue()
    speakingduration = re.findall("\d+\.\d+", speakingduration)
    speakingduration = float(speakingduration[0])

    orgdur = io.StringIO()
    with redirect_stdout(orgdur):
        mysp.myspod(p, c)
    originalduration = orgdur.getvalue()
    originalduration = re.findall("\d+\.\d+", originalduration)
    originalduration = float(originalduration[0])

    speechpercentage = (speakingduration/originalduration)*100

    moodtemp = io.StringIO()
    with redirect_stdout(moodtemp):
        mysp.myspgend(p, c)
    tone = ""
    mood = moodtemp.getvalue()
    print(mood)
    if "Showing no emotion" in mood:
        tone = "Emotionless"
    elif "Reading" in mood:
        tone = "Reading"
    elif "passionately" in mood:
        tone = "Passionate"

    analytics = {
        "wpm": speechrate,
        "pauses": pauses,
        "speechpercent": speechpercentage,
        "tone": tone,
        "redundancy":{}
    }
    take.update_one({"practiceid": practiceid}, {
                    "$set": {"analytics": analytics}})
    return jsonify({"message": "success"})

@app.route("/sendvid/<path:path>",methods=["GET"])
def sendvid(path):
    return send_from_directory("uploads",path)



if __name__ == "__main__":
    app.run(debug=True)