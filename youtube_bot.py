import os
import json
import shutil
import asyncio
import subprocess
import requests
import datetime
import math
import feedparser
import pytz
import edge_tts
from moviepy.editor import (
    VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip,
    TextClip, ColorClip, CompositeAudioClip, concatenate_videoclips
)
from moviepy.video.fx.all import colorx, fadein, fadeout
from PIL import Image, ImageDraw, ImageFont

# YouTube API Imports
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- CONFIGURATION ---
LANGUAGES = {
    "English": {"tts": "en-IN-NeerjaNeural", "gemini_lang": "Indian English", "font": "Noto Sans Bold"}
}

BLOCKED_KEYWORDS = ["war", "dead", "death", "kill", "attack", "suicide", "terror", "blood", "gore", "shoot", "bomb", "tragedy", "casualt"]
STOP_WORDS = ["the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "were"]

# --- YOUTUBE UPLOAD FUNCTION ---
def upload_to_youtube(video_path, title, description, tags):
    print(f"📤 Uploading {video_path} to YouTube...")
    if not os.path.exists("token.json"):
        print("❌ token.json not found! Skipping upload.")
        return

    creds = Credentials.from_authorized_user_file("token.json")
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "28"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"   Upload progress: {int(status.progress() * 100)}%")

    video_id = response['id']
    print(f"✅ Uploaded successfully! Video ID: {video_id}")
    print(f"🔗 https://youtube.com/watch?v={video_id}")
    return video_id

# --- 0. UTILITIES ---
def get_system_font(font_name):
    try:
        result = subprocess.run(['fc-match', '-f', '%{file}', font_name], capture_output=True, text=True)
        if result.stdout and result.stdout.strip(): return result.stdout.strip()
    except Exception: pass
    return "Roboto-Bold.ttf"

def fetch_background_images(headlines):
    print("🖼️ Fetching relevant background images for stories...")
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY")}
    image_paths = []
    
    for i, headline in enumerate(headlines[:5]):
        words = [word for word in headline.split() if word.lower() not in STOP_WORDS]
        search_query = " ".join(words[:3]) if words else "technology"
        try:
            r = requests.get(f"https://api.pexels.com/v1/search?query={search_query}&per_page=1", headers=headers, timeout=15)
            if r.status_code == 200 and r.json()['photos']:
                img_url = r.json()['photos'][0]['src']['large']
                img_data = requests.get(img_url, timeout=15).content
                path = f"bg_{i}.jpg"
                with open(path, "wb") as f: f.write(img_data)
                image_paths.append(path)
            else:
                ColorClip(size=(1920, 1080), color=(10, 10, 20)).save_frame(f"bg_{i}.jpg")
                image_paths.append(f"bg_{i}.jpg")
        except:
            ColorClip(size=(1920, 1080), color=(10, 10, 20)).save_frame(f"bg_{i}.jpg")
            image_paths.append(f"bg_{i}.jpg")
    return image_paths

def is_safe(text):
    for word in BLOCKED_KEYWORDS:
        if word in text.lower(): return False
    return True

# --- 1. NEWS FETCHER ---
def get_fresh_news():
    print("📰 Fetching latest Future Intelligence news...")
    url = "https://news.google.com/rss/search?q=artificial+intelligence+stocks+OR+crypto+news+OR+tech+business+latest+news&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    
    history = []
    if os.path.exists("news_history.json"):
        with open("news_history.json", "r") as f: history = json.load(f)
            
    utc_now = datetime.datetime.now(pytz.UTC)
    cutoff_time = utc_now - datetime.timedelta(hours=48)
    history = [h for h in history if datetime.datetime.fromisoformat(h["timestamp"]) > cutoff_time]
    
    fresh_news = []
    for entry in feed.entries:
        pub_date = datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.UTC)
        if (utc_now - pub_date) > datetime.timedelta(hours=24): continue
        title_clean = entry.title.split(" - ")[0]
        if any(h["title"] == title_clean for h in history) or not is_safe(title_clean): continue
        fresh_news.append(title_clean)
        history.append({"title": title_clean, "timestamp": utc_now.isoformat()})
        if len(fresh_news) >= 5: break
            
    with open("news_history.json", "w") as f: json.dump(history, f, indent=4)
    return fresh_news

# --- 2. GEMINI API ---
def call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return ""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key.strip()}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192}
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"❌ API call failed: {e}")
        return ""

def generate_content(headlines, language_name, gemini_lang):
    print(f"📝 Generating scripts & metadata for {language_name}...")
    ist_time = datetime.datetime.now(pytz.UTC) + datetime.timedelta(hours=5, minutes=30)
    time_of_day = "morning" if ist_time.hour < 12 else "evening"
    current_date_str = ist_time.strftime("%A, %B %d, %Y")
    
    prompt = f"""
    You are an energetic, casual tech news anchor for 'Future Intelligence News' in India.
    Write a highly detailed 800-word broadcast script in **{gemini_lang}** based on these headlines: {headlines}.
    Use conversational Indian English slang (e.g., "guys", "let's break this down", "mind-blowing stuff"). 
    
    FOLLOW THIS EXACT BROADCAST STRUCTURE:
    [INTRODUCTION] Welcome viewers. Mention today's exact date ({current_date_str}) and {time_of_day} broadcast.
    [HEADLINES] List top 3-4 stories in one sentence each.
    [DETAILED NEWS] Go deep into each story (1 min each).
    [CLOSING] Summarize biggest takeaway. Thank viewers.
    [NEXT TIME HINT] Tease next broadcast.
    
    ALSO GENERATE:
    1. A 150-word version of this script for a 60-second YouTube Short.
    2. A YouTube Title (Max 60 chars) that creates a MASSIVE CURIOSITY GAP.
    3. A YouTube Description with chapters (0:00 Intro, 1:00 Story 1, etc.) and 5 SEO Tags.
    4. A short 5-8 word Breaking News Ticker text in {gemini_lang}.
    
    Format output strictly as:
    [LONG_SCRIPT]
    <script here>
    [SHORT_SCRIPT]
    <short script here>
    [METADATA]
    Title: ...
    Description: ...
    Tags: tag1, tag2, tag3
    [TICKER_TEXT]
    <ticker text here>
    """
    return call_gemini(prompt)

# --- 3. EDGE-TTS ---
async def _generate_voice_async(text, tts_voice, srt_path, audio_path):
    communicate = edge_tts.Communicate(text, tts_voice)
    submaker = edge_tts.SubMaker()
    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio": audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                try: submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
                except: pass
    try:
        with open(srt_path, "w", encoding='utf-8') as f: f.write(submaker.generate_subs())
    except:
        with open(srt_path, "w", encoding='utf-8') as f: f.write("1\n00:00:00,000 --> 00:00:10,000\nSubtitles unavailable\n")

def generate_voice_and_subs(text, lang_name, tts_voice, prefix="temp"):
    audio_path = f"{prefix}_voice_{lang_name}.mp3"
    srt_path = f"subtitles_{lang_name}.srt" if prefix == "final" else f"{prefix}_subs_{lang_name}.srt"
    asyncio.run(_generate_voice_async(text, tts_voice, srt_path, audio_path))
    return audio_path, srt_path

# --- 4. 5-MINUTE VALIDATION LOOP (Optimized for speed) ---
def generate_and_validate_voice(script, lang_name, gemini_lang, tts_voice, headlines):
    max_attempts, attempt, current_script = 2, 0, script
    while attempt < max_attempts:
        audio_file, srt_file = generate_voice_and_subs(current_script, lang_name, tts_voice, "final")
        duration = AudioFileClip(audio_file).duration
        print(f"⏱️ Validation Check: Audio is {duration/60:.2f} minutes long.")
        # FIX: Changed to 300 seconds (5 minutes) to reduce load
        if duration >= 300: return audio_file, srt_file
        attempt += 1
        extra = call_gemini(f"The following {gemini_lang} script is too short. Add 300 words of deep analysis about {headlines} before the closing. Return ONLY the new text.\n\nScript: {current_script}")
        current_script = current_script.replace("[CLOSING]", f"{extra}\n\n[CLOSING]")
        os.remove(audio_file); os.remove(srt_file)
    return generate_voice_and_subs(current_script, lang_name, tts_voice, "final")

# --- 5. VIDEO ASSEMBLY ---
def assemble_long_video(audio_file, ticker_text, lang_name, headlines, font_path, image_paths):
    print(f"🎬 Assembling Long-form {lang_name} Broadcast...")
    audio = AudioFileClip(audio_file)
    duration = audio.duration

    bg_clips = []
    for i, img_path in enumerate(image_paths):
        clip = ImageClip(img_path).fx(colorx, 0.6).resize((1920, 1080)).set_duration(duration/len(image_paths))
        if i > 0: clip = clip.fx(fadein, 0.5)
        if i < len(image_paths)-1: clip = clip.fx(fadeout, 0.5)
        bg_clips.append(clip)
    bg = concatenate_videoclips(bg_clips, method="compose", padding=-0.5)

    layers = [bg]
    if os.path.exists("my_photo.png"):
        layers.append(ImageClip("my_photo.png").set_duration(duration).set_position(("right", "top")).resize(height=350))

    layers.append(TextClip("FUTURE INTELLIGENCE NEWS", fontsize=36, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(duration).set_position((20, 20)))
    layers.append(ColorClip(size=(20, 20), color=(220, 0, 0)).set_duration(duration).set_position((20, 70)))
    layers.append(TextClip("LIVE", fontsize=24, color='white', font=font_path, stroke_color='red', stroke_width=1).set_duration(duration).set_position((50, 68)))
    
    ist_time = datetime.datetime.now(pytz.UTC) + datetime.timedelta(hours=5, minutes=30)
    layers.append(TextClip(ist_time.strftime("%H:%M:%S IST"), fontsize=22, color='white', font=font_path).set_duration(duration).set_position((20, 100)))

    layers.append(ColorClip(size=(1920, 80), color=(180, 0, 0)).set_duration(duration).set_position(("center", "bottom")))
    layers.append(TextClip("BREAKING", fontsize=36, color='black', font=font_path).set_duration(duration).set_position((10, 1010)))
    
    ticker_clip = TextClip(ticker_text, fontsize=38, color='white', font=font_path).set_duration(duration)
    ticker_speed = (ticker_clip.w + 1920) / duration
    layers.append(ticker_clip.set_position(lambda t: (1920 - ticker_speed * t, 1010)))

    final_video = CompositeVideoClip(layers).set_audio(audio)
    output_file = f"final_news_{lang_name}.mp4"
    final_video.write_videofile(output_file, codec="libx264", audio_codec="aac", fps=24, threads=4, preset="ultrafast")
    os.remove(audio_file)
    return output_file

def assemble_shorts(short_script, lang_name, tts_voice, font_path, image_paths):
    print(f"📱 Assembling {lang_name} Short...")
    audio_file = f"short_voice_{lang_name}.mp3"
    asyncio.run(_generate_voice_async(short_script, tts_voice, f"short_subs_{lang_name}.srt", audio_file))
    audio = AudioFileClip(audio_file).subclip(0, min(AudioFileClip(audio_file).duration, 55))

    bg = ImageClip(image_paths[0]).fx(colorx, 0.6).resize((1080, 1920)).set_duration(audio.duration)
    layers = [bg]
    if os.path.exists("my_photo.png"):
        layers.append(ImageClip("my_photo.png").set_duration(audio.duration).set_position(("center", "bottom")).resize(height=500))
    layers.append(TextClip("FUTURE INTELLIGENCE", fontsize=50, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(audio.duration).set_position(("center", 0.1)))

    output_file = f"shorts_{lang_name}.mp4"
    CompositeVideoClip(layers).set_audio(audio).write_videofile(output_file, codec="libx264", audio_codec="aac", fps=24, threads=4, preset="ultrafast")
    os.remove(audio_file)
    return output_file

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    fresh_news = get_fresh_news()
    if not fresh_news: exit()

    image_paths = fetch_background_images(fresh_news)
    
    for lang_name, lang_data in LANGUAGES.items():
        print(f"\n--- Processing {lang_name} Channel ---")
        raw_output = generate_content(fresh_news, lang_name, lang_data["gemini_lang"])
        if not raw_output: continue
            
        try:
            long_script = raw_output.split("[LONG_SCRIPT]")[1].split("[SHORT_SCRIPT]")[0].strip()
            short_script = raw_output.split("[SHORT_SCRIPT]")[1].split("[METADATA]")[0].strip()
            metadata = raw_output.split("[METADATA]")[1].split("[TICKER_TEXT]")[0].strip()
            ticker_text = raw_output.split("[TICKER_TEXT]")[1].strip().split("\n")[0]
            
            # Parse metadata
            title = [l for l in metadata.split('\n') if l.startswith('Title:')][0].replace('Title:', '').strip()
            description = "\n".join([l for l in metadata.split('\n') if l.startswith('Description:')]).replace('Description:', '').strip()
            tags_line = [l for l in metadata.split('\n') if l.startswith('Tags:')][0].replace('Tags:', '').strip()
            tags = [t.strip() for t in tags_line.split(',')]
            
        except Exception as e:
            print(f"❌ Error parsing output: {e}")
            continue

        audio_file, srt_file = generate_and_validate_voice(long_script, lang_name, lang_data["gemini_lang"], lang_data["tts"], fresh_news)
        long_video = assemble_long_video(audio_file, ticker_text, lang_name, fresh_news, get_system_font(lang_data["font"]), image_paths)
        short_video = assemble_shorts(short_script, lang_name, lang_data["tts"], get_system_font(lang_data["font"]), image_paths)
        
        # --- AUTOMATIC UPLOAD ---
        # Upload Long Form
        long_title = f"{title} | Future Intelligence News"
        long_desc = f"{description}\n\n#AI #TechNews #FutureIntelligence"
        upload_to_youtube(long_video, long_title, long_desc, tags)
        os.remove(long_video)
        
        # Upload Short
        short_title = f"🔴 BREAKING: {title}"
        short_desc = f"Watch the full broadcast on our channel! #Shorts #TechNews"
        upload_to_youtube(short_video, short_title, short_desc, tags + ["Shorts", "Short"])
        os.remove(short_video)
        
    print("\n✅ ALL VIDEOS GENERATED AND UPLOADED TO YOUTUBE!")
