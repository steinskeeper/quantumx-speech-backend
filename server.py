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
from nltk.corpus import wordnet
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
    if prev:
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
    script = result["transcribed_script"]
    numwor = len(script.split(" "))

    print(fileb)
    script = result["script"].lower()
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

    wwpm = numwor/(originalduration/60)

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
    
    freq = word_count(script)
    myDict = {key:val for key, val in freq.items() if val > 2}
    print(myDict)
    ps = (myDict.keys())
    rec = {}
    for i in ps:
        synonyms = []
        for syn in wordnet.synsets(i):
            for l in syn.lemmas():
                synonyms.append(l.name())
        s = (set(synonyms))
        s = list(s)
        rec[i] = s
    

    


    analytics = {
        "wpm": wwpm,
        "pauses": pauses,
        "speechpercent": speechpercentage,
        "tone": tone,
        "redundancy": rec
    }
    take.update_one({"practiceid": practiceid}, {
                    "$set": {"analytics": analytics}})
    return jsonify({"message": "success"})

@app.route("/sendvid/<path:path>",methods=["GET"])
def sendvid(path):
    return send_from_directory("uploads",path)

ignore = ["the"
"of",
"to",
"and",
"a",
"in",
"is",
"it",
"you",
"that",
"he",
"was",
"for",
"on",
"are",
"with",
"as",
"I",
"his",
"they",
"be",
"at",
"one",
"have",
"this",
"from",
"or",
"had",
"by",
"not",
"word",
"but",
"what",
"some",
"we",
"can",
"out",
"other",
"were",
"all",
"there",
"when",
"up",
"use",
"your",
"how",
"said",
"an",
"each",
"she",
"which",
"do",
"their",
"time",
"if",
"will",
"way",
"about",
"many",
"then",
"them",
"write",
"would",
"like",
"so",
"these",
"her",
"long",
"make",
"thing",
"see",
"him",
"two",
"has",
"look",
"more",
"day",
"could",
"go",
"come",
"did",
"number",
"sound",
"no",
"most",
"people",
"my",
"over",
"know",
"water",
"than",
"call",
"first",
"who",
"may",
"down",
"side",
"been",
"now",
"find",
"any",
"new",
"work",
"part",
"take",
"get",
"place",
"made",
"live",
"where",
"after",
"back",
"little",
"only",
"round",
"man",
"year",
"came",
"show",
"every",
"good",
"me",
"give",
"our",
"under",
"name",
"very",
"through",
"just",
"form",
"sentence",
"great",
"think",
"say",
"help",
"low",
"line",
"differ",
"turn",
"cause",
"much",
"mean",
"before",
"move",
"right",
"boy",
"old",
"too",
"same",
"tell",
"does",
"set",
"three",
"want",
"air",
"well",
"also",
"play",
"small",
"end",
"put",
"home",
"read",
"hand",
"port",
"large",
"spell",
"add",
"even",
"land",
"here",
"must",
"big",
"high",
"such",
"follow",
"act",
"why",
"ask",
"men",
"change",
"went",
"light",
"kind",
"off",
"need",
"house",
"picture",
"try",
"us",
"again",
"animal",
"point",
"mother",
"world",
"near",
"build",
"self",
"earth",
"father",
"head",
"stand",
"own",
"page",
"should",
"country",
"found",
"answer",
"school",
"grow",
"study",
"still",
"learn",
"plant",
"cover",
"food",
"sun",
"four",
"between",
"state",
"keep",
"eye",
"never",
"last",
"let",
"thought",
"city",
"tree",
"cross",
"farm",
"hard",
"start",
"might",
"story",
"saw",
"far",
"sea",
"draw",
"left",
"late",
"run",
"don't",
"while",
"press",
"close",
"night",
"real",
"life",
"few",
"north",
"open",
"seem",
"together",
"next",
"white",
"children",
"begin",
"got",
"walk",
"example",
"ease",
"paper",
"group",
"always",
"music",
"those",
"both",
"mark",
"often",
"letter",
"until",
"mile",
"river",
"car",
"feet",
"care",
"second",
"book",
"carry",
"took",
"science",
"eat",
"room",
"friend",
"began",
"idea",
"fish",
"mountain",
"stop",
"once",
"base",
"hear",
"horse",
"cut",
"sure",
"watch",
"color",
"face",
"wood",
"main",
"enough",
"plain",
"girl",
"usual",
"young",
"ready",
"above",
"ever",
"red",
"list",
"though",
"feel",
"talk",
"bird",
"soon",
"body",
"dog",
"family",
"direct",
"pose",
"leave",
"song",
"measure",
"door",
"product",
"black",
"short",
"numeral",
"class",
"wind",
"question",
"happen",
"complete",
"ship",
"area",
"half",
"rock",
"order",
"fire",
"south",
"problem",
"piece",
"told",
"knew",
"pass",
"since",
"top",
"whole",
"king",
"space",
"heard",
"best",
"hour",
"better",
"true",
"during",
"hundred",
"five",
"remember",
"step",
"early",
"hold",
"west",
"ground",
"interest",
"reach",
"fast",
"verb",
"sing",
"listen",
"six",
"table",
"travel",
"less",
"morning",
"ten",
"simple",
"several",
"vowel",
"toward",
"war",
"lay",
"against",
"pattern",
"slow",
"center",
"love",
"person",
"money",
"serve",
"appear",
"road",
"map",
"rain",
"rule",
"govern",
"pull",
"cold",
"notice",
"voice",
"unit",
"power",
"town",
"fine",
"certain",
"fly",
"fall",
"lead",
"cry",
"dark",
"machine",
"note",
"wait",
"plan",
"figure",
"star",
"box",
"noun",
"field",
"rest",
"correct",
"able",
"pound",
"done",
"beauty",
"drive",
"stood",
"contain",
"front",
"teach",
"week",
"final",
"gave",
"green",
"oh",
"quick",
"develop",
"ocean",
"warm",
"free",
"minute",
"strong",
"special",
"mind",
"behind",
"clear",
"tail",
"produce",
"fact",
"street",
"inch",
"multiply",
"nothing",
"course",
"stay",
"wheel",
"full",
"force",
"blue",
"object",
"decide",
"surface",
"deep",
"moon",
"island",
"foot",
"system",
"busy",
"test",
"record",
"boat",
"common",
"gold",
"possible",
"plane",
"stead",
"dry",
"wonder",
"laugh",
"thousand",
"ago",
"ran",
"check",
"game",
"shape",
"equate",
"hot",
"miss",
"brought",
"heat",
"snow",
"tire",
"bring",
"yes",
"distant",
"fill",
"east",
"paint",
"language",
"among",
"grand",
"ball",
"yet",
"wave",
"drop",
"heart",
"am",
"present",
"heavy",
"dance",
"engine",
"position",
"arm",
"wide",
"sail",
"material",
"size",
"vary",
"settle",
"speak",
"weight",
"general",
"ice",
"matter",
"circle",
"pair",
"include",
"divide",
"syllable",
"felt",
"perhaps",
"pick",
"sudden",
"count",
"square",
"reason",
"length",
"represent",
"art",
"subject",
"region",
"energy",
"hunt",
"probable",
"bed",
"brother",
"egg",
"ride",
"cell",
"believe",
"fraction",
"forest",
"sit",
"race",
"window",
"store",
"summer",
"train",
"sleep",
"prove",
"lone",
"leg",
"exercise",
"wall",
"catch",
"mount",
"wish",
"sky",
"board",
"joy",
"winter",
"sat",
"written",
"wild",
"instrument",
"kept",
"glass",
"grass",
"cow",
"job",
"edge",
"sign",
"visit",
"past",
"soft",
"fun",
"bright",
"gas",
"weather",
"month",
"million",
"bear",
"finish",
"happy",
"hope",
"flower",
"clothe",
"strange",
"gone",
"jump",
"baby",
"eight",
"village",
"meet",
"root",
"buy",
"raise",
"solve",
"metal",
"whether",
"push",
"seven",
"paragraph",
"third",
"shall",
"held",
"hair",
"describe",
"cook",
"floor",
"either",
"result",
"burn",
"hill",
"safe",
"cat",
"century",
"consider",
"type",
"law",
"bit",
"coast",
"copy",
"phrase",
"silent",
"tall",
"sand",
"soil",
"roll",
"temperature",
"finger",
"industry",
"value",
"fight",
"lie",
"beat",
"excite",
"natural",
"view",
"sense",
"ear",
"else",
"quite",
"broke",
"case",
"middle",
"kill",
"son",
"lake",
"moment",
"scale",
"loud",
"spring",
"observe",
"child",
"straight",
"consonant",
"nation",
"dictionary",
"milk",
"speed",
"method",
"organ",
"pay",
"age",
"section",
"dress",
"cloud",
"surprise",
"quiet",
"stone",
"tiny",
"climb",
"cool",
"design",
"poor",
"lot",
"experiment",
"bottom",
"key",
"iron",
"single",
"stick",
"flat",
"twenty",
"skin",
"smile",
"crease",
"hole",
"trade",
"melody",
"trip",
"office",
"receive",
"row",
"mouth",
"exact",
"symbol",
"die",
"least",
"trouble",
"shout",
"except",
"wrote",
"seed",
"tone",
"join",
"suggest",
"clean",
"break",
"lady",
"yard",
"rise",
"bad",
"blow",
"oil",
"blood",
"touch",
"grew",
"cent",
"mix",
"team",
"wire",
"cost",
"lost",
"brown",
"wear",
"garden",
"equal",
"sent",
"choose",
"fell",
"fit",
"flow",
"fair",
"bank",
"collect",
"save",
"control",
"decimal",
"gentle",
"woman",
"captain",
"practice",
"separate",
"difficult",
"doctor",
"please",
"protect",
"noon",
"whose",
"locate",
"ring",
"character",
"insect",
"caught",
"period",
"indicate",
"radio",
"spoke",
"atom",
"human",
"history",
"effect",
"electric",
"expect",
"crop",
"modern",
"element",
"hit",
"student",
"corner",
"party",
"supply",
"bone",
"rail",
"imagine",
"provide",
"agree",
"thus",
"capital",
"won't",
"chair",
"danger",
"fruit",
"rich",
"thick",
"soldier",
"process",
"operate",
"guess",
"necessary",
"sharp",
"wing",
"create",
"neighbor",
"wash",
"bat",
"rather",
"crowd",
"corn",
"compare",
"poem",
"string",
"bell",
"depend",
"meat",
"rub",
"tube",
"famous",
"dollar",
"stream",
"fear",
"sight",
"thin",
"triangle",
"planet",
"hurry",
"chief",
"colony",
"clock",
"mine",
"tie",
"enter",
"major",
"fresh",
"search",
"send",
"yellow",
"gun",
"allow",
"print",
"dead",
"spot",
"desert",
"suit",
"current",
"lift",
"rose",
"continue",
"block",
"chart",
"hat",
"sell",
"success",
"company",
"subtract",
"event",
"particular",
"deal",
"swim",
"term",
"opposite",
"wife",
"shoe",
"shoulder",
"spread",
"arrange",
"camp",
"invent",
"cotton",
"born",
"determine",
"quart",
"nine",
"truck",
"noise",
"level",
"chance",
"gather",
"shop",
"stretch",
"throw",
"shine",
"property",
"column",
"molecule",
"select",
"wrong",
"gray",
"repeat",
"require",
"broad",
"prepare",
"salt",
"nose",
"plural",
"anger",
"claim",
"continent",
"oxygen",
"sugar",
"death",
"pretty",
"skill",
"women",
"season",
"solution",
"magnet",
"silver",
"thank",
"branch",
"match",
"suffix",
"especially",
"fig",
"afraid",
"huge",
"sister",
"steel",
"discuss",
"forward",
"similar",
"guide",
"experience",
"score",
"apple",
"bought",
"led",
"pitch",
"coat",
"mass",
"card",
"band",
"rope",
"slip",
"win",
"dream",
"evening",
"condition",
"feed",
"tool",
"total",
"basic",
"smell",
"valley",
"nor",
"double",
"seat",
"arrive",
"master",
"track",
"parent",
"shore",
"division",
"sheet",
"substance",
"favor",
"connect",
"post",
"spend",
"chord",
"fat",
"glad",
"original",
"share",
"station",
"dad",
"bread",
"charge",
"proper",
"bar",
"offer",
"segment",
"slave",
"duck",
"instant",
"market",
"degree",
"populate",
"chick",
"dear",
"enemy",
"reply",
"drink",
"occur",
"support",
"speech",
"nature",
"range",
"steam",
"motion",
"path",
"liquid",
"log",
"meant",
"quotient",
"teeth",
"shell",
"neck",]
def word_count(str):
    counts = dict()
    words = str.split()


    for word in words:
        if word in ignore:
            continue
        elif word in counts:
            counts[word] += 1
        else:
            counts[word] = 1

    return counts





if __name__ == "__main__":
    app.run(debug=True)
