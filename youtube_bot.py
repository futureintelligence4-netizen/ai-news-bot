import os
import json
import shutil
import asyncio
import subprocess
import requests
import datetime
import sys
import feedparser
import pytz
import edge_tts
import urllib.parse
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

# --- MOVIEPY IMAGEMAGICK FIX ---
import moviepy.config as mp_config
if shutil.which("convert"):
    mp_config.change_settings({"IMAGEMAGICK_BINARY": shutil.which("convert")})

# --- PILLOW COMPATIBILITY PATCH ---
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'): PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

# --- CONFIGURATION ---
CHANNELS = {
    "FutureIntelligence": {
        "name": "Future Intelligence News",
        "news_query": "artificial+intelligence+stocks+OR+tech+business+latest+news",
        "gemini_lang": "Indian English",
        "tts": "en-IN-NeerjaNeural",
        "font": "Noto Sans Bold",
        "token_env": "YOUTUBE_TOKEN"
    },
    "CryptoNews": {
        "name": "Crypto News Daily",
        "news_query": "cryptocurrency+OR+bitcoin+OR+web3+latest+news",
        "gemini_lang": "Indian English",
        "tts": "en-IN-NeerjaNeural",
        "font": "Noto Sans Bold",
        "token_env": "YOUTUBE_TOKEN_2"
    }
}

BLOCKED_KEYWORDS = ["war", "dead", "death", "kill", "attack", "suicide", "terror", "blood", "gore", "shoot", "bomb", "tragedy", "casualt"]
STOP_WORDS = ["the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "were"]

# --- YOUTUBE UPLOAD ---
def upload_to_youtube(video_path, title, description, tags, token_env):
    print(f"📤 Uploading {video_path} to YouTube...")
    token_json_str = os.environ.get(token_env)
    if not token_json_str:
        print(f"❌ {token_env} not found in secrets! Skipping upload.")
        return

    with open("temp_token.json", "w") as f: f.write(token_json_str)
    creds = Credentials.from_authorized_user_file("temp_token.json")
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {"title": title[:100], "description": description, "tags": tags, "categoryId": "28"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True))

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status: print(f"   Upload progress: {int(status.progress() * 100)}%")

    print(f"✅ Uploaded successfully! Video ID: {response['id']}")
    os.remove("temp_token.json")

# --- UTILITIES ---
def get_system_font(font_name):
    try:
        result = subprocess.run(['fc-match', '-f', '%{file}', font_name], capture_output=True, text=True)
        if result.stdout and result.stdout.strip(): return result.stdout.strip()
    except: pass
    return "Roboto-Bold.ttf"

def fetch_ai_thumbnail_image(headline):
    print("🖼️ Generating AI Thumbnail Background...")
    prompt = f"{headline}, futuristic technology, digital art, cinematic lighting, 4k, no text"
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            with open("thumb_bg.jpg", "wb") as f: f.write(r.content)
            return "thumb_bg.jpg"
    except: pass
    return None

def fetch_background_images(headlines):
    print("🖼️ Fetching relevant background images...")
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY")}
    image_paths = []
    for i, headline in enumerate(headlines[:5]):
        words = [word for word in headline.split() if word.lower() not in STOP_WORDS]
        search_query = " ".join(words[:3]) if words else "technology"
        try:
            r = requests.get(f"https://api.pexels.com/v1/search?query={search_query}&per_page=1", headers=headers, timeout=15)
            if r.status_code == 200 and r.json()['photos']:
                img_data = requests.get(r.json()['photos'][0]['src']['large'], timeout=15).content
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

# --- NEWS FETCHER ---
def get_fresh_news(news_query):
    print(f"📰 Fetching latest news for: {news_query}...")
    url = f"https://news.google.com/rss/search?q={news_query}&hl=en-US&gl=US&ceid=US:en"
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

# --- GEMINI API ---
def call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return ""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key.strip()}
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192}}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"❌ API call failed: {e}")
        return ""

def generate_content(channel_name, headlines, gemini_lang):
    print(f"📝 Generating script for {channel_name}...")
    ist_time = datetime.datetime.now(pytz.UTC) + datetime.timedelta(hours=5, minutes=30)
    time_of_day = "morning" if ist_time.hour < 12 else "evening"
    current_date_str = ist_time.strftime("%A, %B %d, %Y")
    prompt = f"""
    You are an energetic, casual tech news anchor for '{channel_name}' in India.
    Write a highly detailed 800-word broadcast script in **{gemini_lang}** based on these headlines: {headlines}.
    Use conversational Indian English slang. 
    [INTRODUCTION] Welcome viewers. Mention today's exact date ({current_date_str}) and {time_of_day} broadcast.
    [HEADLINES] List top 3-4 stories.
    [DETAILED NEWS] Go deep into each story.
    [CLOSING] Summarize biggest takeaway.
    [NEXT TIME HINT] Tease next broadcast.
    ALSO GENERATE:
    1. A 150-word version for a 60-second YouTube Short.
    2. A YouTube Title (Max 60 chars) that creates a MASSIVE CURIOSITY GAP.
    3. A YouTube Description with chapters and 5 SEO Tags.
    4. A short 5-8 word Breaking News Ticker text.
    Format output strictly as:
    [LONG_SCRIPT] <script> [SHORT_SCRIPT] <script> [METADATA] Title: ... Description: ... Tags: ... [TICKER_TEXT] <text>
    """
    return call_gemini(prompt)

# --- EDGE-TTS ---
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

def generate_voice_and_subs(text, tag, tts_voice, prefix="temp"):
    audio_path = f"{prefix}_voice_{tag}.mp3"
    srt_path = f"subtitles_{tag}.srt" if prefix == "final" else f"{prefix}_subs_{tag}.srt"
    asyncio.run(_generate_voice_async(text, tts_voice, srt_path, audio_path))
    return audio_path, srt_path

# --- VIDEO ASSEMBLY ---
def assemble_long_video(audio_file, ticker_text, tag, font_path, image_paths):
    print(f"🎬 Assembling Long-form {tag}...")
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
    layers.append(TextClip(tag.upper(), fontsize=36, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(duration).set_position((20, 20)))
    layers.append(ColorClip(size=(20, 20), color=(220, 0, 0)).set_duration(duration).set_position((20, 70)))
    layers.append(TextClip("LIVE", fontsize=24, color='white', font=font_path, stroke_color='red', stroke_width=1).set_duration(duration).set_position((50, 68)))
    ist_time = datetime.datetime.now(pytz.UTC) + datetime.timedelta(hours=5, minutes=30)
    layers.append(TextClip(ist_time.strftime("%H:%M:%S IST"), fontsize=22, color='white', font=font_path).set_duration(duration).set_position((20, 100)))
    layers.append(ColorClip(size=(1920, 80), color=(180, 0, 0)).set_duration(duration).set_position(("center", "bottom")))
    layers.append(TextClip("BREAKING", fontsize=36, color='black', font=font_path).set_duration(duration).set_position((10, 1010)))
    ticker_clip = TextClip(ticker_text, fontsize=38, color='white', font=font_path).set_duration(duration)
    ticker_speed = (ticker_clip.w + 1920) / duration
    layers.append(ticker_clip.set_position(lambda t: (1920 - ticker_speed * t, 1010)))
    output_file = f"final_news_{tag}.mp4"
    CompositeVideoClip(layers).set_audio(audio).write_videofile(output_file, codec="libx264", audio_codec="aac", fps=24, threads=4, preset="ultrafast")
    os.remove(audio_file)
    return output_file

def assemble_shorts(short_script, tag, tts_voice, font_path, image_paths):
    print(f"📱 Assembling {tag} Short...")
    audio_file = f"short_voice_{tag}.mp3"
    asyncio.run(_generate_voice_async(short_script, tts_voice, f"short_subs_{tag}.srt", audio_file))
    
    # FIX: Load audio once to prevent memory leaks
    audio_raw = AudioFileClip(audio_file)
    duration = min(audio_raw.duration, 55)
    audio = audio_raw.subclip(0, duration)

    bg = ImageClip(image_paths[0]).fx(colorx, 0.6).resize((1080, 1920)).set_duration(audio.duration)
    layers = [bg]
    if os.path.exists("my_photo.png"):
        layers.append(ImageClip("my_photo.png").set_duration(audio.duration).set_position(("center", "bottom")).resize(height=500))
    layers.append(TextClip(tag.upper(), fontsize=50, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(audio.duration).set_position(("center", 0.1)))
    output_file = f"shorts_{tag}.mp4"
    CompositeVideoClip(layers).set_audio(audio).write_videofile(output_file, codec="libx264", audio_codec="aac", fps=24, threads=4, preset="ultrafast")
    os.remove(audio_file)
    return output_file

def generate_thumbnail(tag, top_headline, font_path, thumb_bg_path):
    print(f"🖼️ Generating {tag} Thumbnail...")
    W, H = 1280, 720
    try: img = Image.open(thumb_bg_path).resize((W, H))
    except: img = Image.new('RGB', (W, H), color=(5, 5, 15))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, W, H], fill=(0, 0, 0, 160)) 
    draw.rectangle([0, 0, W, 90], fill=(220, 0, 0, 255))
    font_banner = ImageFont.truetype(font_path, 50)
    draw.text((40, 15), "BREAKING NEWS", fill="white", font=font_banner)
    font_headline = ImageFont.truetype(font_path, 65)
    words = top_headline.split()
    lines, current_line = [], ""
    for word in words:
        test_line = (current_line + " " + word).strip()
        bbox = draw.textbbox((0,0), test_line, font=font_headline)
        if bbox[2] - bbox[0] <= 1150: current_line = test_line
        else:
            if current_line: lines.append(current_line)
            current_line = word
    if current_line: lines.append(current_line)
    y = 250
    for line in lines[:4]:
        draw.text((42, y+2), line, fill=(0,0,0), font=font_headline)
        draw.text((40, y), line, fill="yellow", font=font_headline)
        y += 75
    draw.rectangle([0, 650, W, H], fill=(200, 0, 0, 255))
    font_channel = ImageFont.truetype(font_path, 35)
    draw.text((40, 665), tag.upper(), fill="white", font=font_channel)
    output_file = f"thumbnail_{tag}.jpg"
    img.save(output_file, quality=95)
    return output_file

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    target_channel = sys.argv[1] if len(sys.argv) > 1 else "FutureIntelligence"
    if target_channel not in CHANNELS:
        print(f"❌ Channel {target_channel} not found!"); exit()

    config = CHANNELS[target_channel]
    print(f"\n=== STARTING CHANNEL: {config['name']} ===")
    
    fresh_news = get_fresh_news(config["news_query"])
    if not fresh_news: print("❌ No fresh news. Exiting."); exit()

    image_paths = fetch_background_images(fresh_news)
    thumb_bg = fetch_ai_thumbnail_image(fresh_news[0])
    if not thumb_bg: thumb_bg = image_paths[0]
    
    raw_output = generate_content(config["name"], fresh_news, config["gemini_lang"])
    if not raw_output: exit()
        
    # FIX: Bulletproof parsing to prevent IndexError crashes
    try:
        long_script = raw_output.split("[LONG_SCRIPT]")[1].split("[SHORT_SCRIPT]")[0].strip() if "[LONG_SCRIPT]" in raw_output else ""
        short_script = raw_output.split("[SHORT_SCRIPT]")[1].split("[METADATA]")[0].strip() if "[SHORT_SCRIPT]" in raw_output else ""
        metadata = raw_output.split("[METADATA]")[1].split("[TICKER_TEXT]")[0].strip() if "[METADATA]" in raw_output else ""
        ticker_text = raw_output.split("[TICKER_TEXT]")[1].strip().split("\n")[0] if "[TICKER_TEXT]" in raw_output else "Breaking News"
        
        title = "Tech News Update"
        description = "Latest technology news."
        tags = ["tech", "news"]
        
        if "Title:" in metadata:
            title = [l for l in metadata.split('\n') if l.startswith('Title:')][0].replace('Title:', '').strip()
        if "Description:" in metadata:
            description = "\n".join([l for l in metadata.split('\n') if l.startswith('Description:')]).replace('Description:', '').strip()
        if "Tags:" in metadata:
            tags_line = [l for l in metadata.split('\n') if l.startswith('Tags:')][0].replace('Tags:', '').strip()
            tags = [t.strip() for t in tags_line.split(',')]
            
    except Exception as e:
        print(f"❌ Error parsing output: {e}"); exit()

    audio_file, srt_file = generate_voice_and_subs(long_script, target_channel, config["tts"], "final")
    long_video = assemble_long_video(audio_file, ticker_text, target_channel, get_system_font(config["font"]), image_paths)
    short_video = assemble_shorts(short_script, target_channel, config["tts"], get_system_font(config["font"]), image_paths)
    thumb_file = generate_thumbnail(target_channel, fresh_news[0], get_system_font(config["font"]), thumb_bg)
    
    upload_to_youtube(long_video, f"{title} | {config['name']}", f"{description}\n\n#AI #TechNews #{target_channel}", tags, config["token_env"])
    if os.path.exists(long_video): os.remove(long_video)
    
    upload_to_youtube(short_video, f"🔴 BREAKING: {title}", "Watch the full broadcast! #Shorts", tags + ["Shorts"], config["token_env"])
    if os.path.exists(short_video): os.remove(short_video)
        
    print(f"\n✅ {config['name']} PROCESSED SUCCESSFULLY!")
