import os
import asyncio
import subprocess
import requests
import datetime
import json
import math
import feedparser
import pytz
import edge_tts
from moviepy.editor import (
    VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip,
    TextClip, ColorClip, CompositeAudioClip
)
from moviepy.video.fx.all import colorx
from moviepy.audio.fx.all import volumex
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
LANGUAGES = {
    "English": {"tts": "en-IN-NeerjaNeural", "gemini_lang": "Indian English", "font": "Noto Sans Bold"},
    "Hindi": {"tts": "hi-IN-SwaraNeural", "gemini_lang": "Hindi", "font": "Noto Sans Devanagari Bold"},
    "Tamil": {"tts": "ta-IN-PallaviNeural", "gemini_lang": "Tamil", "font": "Noto Sans Tamil Bold"},
    "Telugu": {"tts": "te-IN-ShrutiNeural", "gemini_lang": "Telugu", "font": "Noto Sans Telugu Bold"},
    "Malayalam": {"tts": "ml-IN-SobhanaNeural", "gemini_lang": "Malayalam", "font": "Noto Sans Malayalam Bold"},
    "Kannada": {"tts": "kn-IN-SapnaNeural", "gemini_lang": "Kannada", "font": "Noto Sans Kannada Bold"}
}

BLOCKED_KEYWORDS = ["war", "dead", "death", "kill", "attack", "suicide", "terror", "blood", "gore", "shoot", "bomb", "tragedy", "casualt"]

# --- 0. DYNAMIC ASSET FETCHERS & UTILITIES ---
def get_system_font(font_name):
    try:
        result = subprocess.run(['fc-match', '-f', '%{file}', font_name], capture_output=True, text=True)
        if result.stdout and result.stdout.strip(): return result.stdout.strip()
    except Exception: pass
    return "Roboto-Bold.ttf"

def fetch_background_music():
    print("🎵 Fetching background music...")
    url = "https://www.soundjay.com/buttons/sounds/button-2.mp3" # Placeholder for CC0 music
    try:
        r = requests.get(url, timeout=10)
        with open("news_theme.mp3", "wb") as f: f.write(r.content)
        return True
    except: return False

def fetch_background_video():
    print("🎥 Fetching dynamic background video...")
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY")}
    try:
        r = requests.get("https://api.pexels.com/videos/search?query=technology&per_page=1", headers=headers, timeout=15)
        if r.status_code == 200 and r.json()['videos']:
            video_url = r.json()['videos'][0]['video_files'][0]['link']
            with open("background_clip.mp4", "wb") as f: f.write(requests.get(video_url).content)
            return True
    except: pass
    ColorClip(size=(1920, 1080), color=(0,0,0)).set_duration(10).write_videofile("background_clip.mp4", fps=24)
    return True

def is_safe(text):
    for word in BLOCKED_KEYWORDS:
        if word in text.lower(): return False
    return True

def prepare_anchor_video():
    """Uses raw FFmpeg to remove green screen and output a transparent WebM."""
    if not os.path.exists("anchor.mp4"):
        print("⚠️ anchor.mp4 not found. Falling back to Live Broadcast Photo Zoom.")
        return None

    print("🟢 Removing green screen from anchor.mp4...")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    output_path = "anchor_transparent.webm"
    
    cmd = [
        ffmpeg_exe, "-y", "-i", "anchor.mp4",
        "-t", "15",
        "-vf", "scale=-1:350,colorkey=0x00FF00:0.3:0.2,format=yuva420p",
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-b:v", "1M",
        "-auto-alt-ref", "0",
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ Anchor green screen removed and ready!")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"⚠️ FFmpeg failed to process anchor: {e}")
        return None

# --- 1. NEWS FETCHER (48h Memory & Safety Filter) ---
def get_fresh_news():
    print("📰 Fetching latest Future Intelligence news...")
    url = "https://news.google.com/rss/search?q=artificial+intelligence+stocks+OR+crypto+news+OR+tech+business+latest+news&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    
    history = []
    if os.path.exists("news_history.json"):
        with open("news_history.json", "r") as f: history = json.load(f)
            
    cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=48)
    history = [h for h in history if datetime.datetime.fromisoformat(h["timestamp"]) > cutoff_time]
    
    fresh_news = []
    now = datetime.datetime.now()
    
    for entry in feed.entries:
        pub_date = datetime.datetime(*entry.published_parsed[:6], tzinfo=pytz.UTC)
        if (now - pub_date.replace(tzinfo=None)) > datetime.timedelta(hours=24): continue
            
        title_clean = entry.title.split(" - ")[0]
        if any(h["title"] == title_clean for h in history) or not is_safe(title_clean): continue
            
        fresh_news.append(title_clean)
        history.append({"title": title_clean, "timestamp": now.isoformat()})
        if len(fresh_news) >= 15: break
            
    with open("news_history.json", "w") as f: json.dump(history, f, indent=4)
    return fresh_news

# --- 2. GEMINI RAW API CALL ---
def call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192}
    }
    try:
        response = requests.post(url, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"❌ Raw API call failed: {e}")
        return ""

def generate_content(headlines, language_name, gemini_lang):
    print(f"📝 Generating scripts & metadata for {language_name} via raw API...")
    time_of_day = "morning" if datetime.datetime.now().hour < 12 else "evening"
    
    prompt = f"""
    You are a top-tier prime-time news anchor for 'Future Intelligence News' in India.
    Write a highly detailed 1,500+ word broadcast script in **{gemini_lang}** based on these latest headlines: {headlines}.
    Do NOT translate literally. Write natively as a local news channel would speak.
    
    FOLLOW THIS EXACT BROADCAST STRUCTURE:
    [INTRODUCTION] Welcome viewers. Mention date and {time_of_day} broadcast.
    [HEADLINES] List top 3-4 stories in one sentence each.
    [DETAILED NEWS] Go deep into each story (2-3 mins each). Provide context and future impact.
    [CLOSING] Summarize biggest takeaway. Thank viewers.
    [NEXT TIME HINT] Tease next broadcast.
    
    ALSO GENERATE:
    1. A 150-word version of this script for a 60-second YouTube Short.
    2. A YouTube Title (Max 70 chars), Description (with 0:00 Intro, 1:30 Story 1 chapters), and 5 Tags.
    3. A short 5-8 word Breaking News Ticker text in {gemini_lang}.
    
    Format output strictly as:
    [LONG_SCRIPT]
    <script here>
    [SHORT_SCRIPT]
    <short script here>
    [METADATA]
    Title: ...
    Description: ...
    Tags: ...
    [TICKER_TEXT]
    <ticker text here>
    """
    return call_gemini(prompt)

# --- 3. EDGE-TTS VOICE & SUBTITLES ---
async def _generate_voice_async(text, tts_voice, srt_path, audio_path):
    communicate = edge_tts.Communicate(text, tts_voice)
    submaker = edge_tts.SubMaker()
    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio": audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary": submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
    with open(srt_path, "w", encoding='utf-8') as f: f.write(submaker.generate_subs())

def generate_voice_and_subs(text, lang_name, tts_voice, prefix="temp"):
    audio_path = f"{prefix}_voice_{lang_name}.mp3"
    srt_path = f"subtitles_{lang_name}.srt" if prefix == "final" else f"{prefix}_subs_{lang_name}.srt"
    asyncio.run(_generate_voice_async(text, tts_voice, srt_path, audio_path))
    return audio_path, srt_path

# --- 4. 8-MINUTE VALIDATION LOOP ---
def generate_and_validate_voice(script, lang_name, gemini_lang, tts_voice, headlines):
    max_attempts, attempt, current_script = 3, 0, script
    while attempt < max_attempts:
        audio_file, srt_file = generate_voice_and_subs(current_script, lang_name, tts_voice, "final")
        duration = AudioFileClip(audio_file).duration
        print(f"⏱️ Validation Check: Audio is {duration/60:.2f} minutes long.")
        if duration >= 480:
            print("✅ Success! Audio is 8+ minutes.")
            return audio_file, srt_file
        attempt += 1
        print(f"⚠️ Failed validation. Requesting more content (Attempt {attempt})...")
        
        ext_prompt = f"The following {gemini_lang} script is too short. Add 500 words of deep analysis about {headlines} before the closing. Return ONLY the new text.\n\nScript: {current_script}"
        extra = call_gemini(ext_prompt)
        
        current_script = current_script.replace("[CLOSING]", f"{extra}\n\n[CLOSING]")
        os.remove(audio_file); os.remove(srt_file)
    return generate_voice_and_subs(current_script, lang_name, tts_voice, "final")

# --- 5. PRO VIDEO ASSEMBLY (LONG FORM) ---
def assemble_long_video(audio_file, ticker_text, lang_name, headlines, font_path, has_music, transparent_anchor_path):
    print(f"🎬 Assembling Long-form {lang_name} Broadcast...")
    audio = AudioFileClip(audio_file)
    duration = audio.duration

    bg = VideoFileClip("background_clip.mp4").resize(height=1080).crop(width=1920)
    bg = bg.loop(duration=duration) if bg.duration < duration else bg.subclip(0, duration)
    bg = bg.fx(colorx, 0.55)

    if has_music and os.path.exists("news_theme.mp3"):
        music = AudioFileClip("news_theme.mp3").fx(volumex, 0.15).audio_loop(duration=duration)
        mixed_audio = CompositeAudioClip([audio, music])
    else: mixed_audio = audio

    # --- ANCHOR SETUP (Video or Live Broadcast Photo Zoom Fallback) ---
    if transparent_anchor_path:
        print("👤 Loading looping video anchor...")
        anchor_raw = VideoFileClip(transparent_anchor_path).without_audio()
        anchor = anchor_raw.loop(duration=duration).set_position(("right", "top"))
    else:
        print("👤 Loading Live Broadcast Zoom photo anchor...")
        raw_anchor = ImageClip("my_photo.png").set_duration(duration).resize(height=350)
        anchor_zoom = raw_anchor.resize(lambda t: 1 + 0.10 * (t / duration))
        def anchor_pos(t):
            y = 0 + 10 * math.sin(t / 2)
            return ("right", y)
        anchor = anchor_zoom.set_position(anchor_pos)

    logo = TextClip("FUTURE INTELLIGENCE NEWS", fontsize=36, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(duration).set_position((20, 20))
    
    live_pulse = lambda t: 0.6 + 0.4 * abs((t % 2) - 1)
    live_dot = ColorClip(size=(20, 20), color=(220, 0, 0)).set_duration(duration).set_position((20, 70))
    live_text = TextClip("LIVE", fontsize=24, color='white', font=font_path, stroke_color='red', stroke_width=1).set_duration(duration).set_position((50, 68)).set_opacity(live_pulse)
    
    ist_time = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    clock = TextClip("00:00:00 IST", fontsize=22, color='white', font=font_path).set_duration(duration).set_position((20, 100))
    clock = clock.set_text(lambda t: (ist_time + datetime.timedelta(seconds=t)).strftime("%H:%M:%S IST"))

    ticker_bg = ColorClip(size=(1920, 80), color=(180, 0, 0)).set_duration(duration).set_position(("center", "bottom"))
    ticker_label = TextClip("BREAKING", fontsize=36, color='black', font=font_path).set_duration(duration).set_position((10, 1010))
    ticker_clip = TextClip(ticker_text, fontsize=38, color='white', font=font_path).set_duration(duration).set_position(lambda t: (1920 - 40 * t, 1010))

    lower_thirds = []
    for i, hl in enumerate(headlines[:3]):
        start = 60 + (i * 120)
        if start < duration:
            lt_bg = ColorClip(size=(1000, 60), color=(0, 0, 0)).set_duration(20).set_position((20, 850)).set_opacity(0.8).set_start(start)
            lt_text = TextClip(hl[:60] + "...", fontsize=28, color='yellow', font=font_path, stroke_color='black', stroke_width=1).set_duration(20).set_position((30, 855)).set_start(start)
            lower_thirds.extend([lt_bg, lt_text])

    final_video = CompositeVideoClip([bg, logo, live_dot, live_text, clock, anchor, ticker_bg, ticker_label, ticker_clip] + lower_thirds).set_audio(mixed_audio)
    
    output_file = f"final_news_{lang_name}.mp4"
    final_video.write_videofile(output_file, codec="libx264", audio_codec="aac", fps=30, threads=4, preset="medium")
    os.remove(audio_file)
    return output_file

# --- 6. SHORTS ASSEMBLY ---
def assemble_shorts(short_script, lang_name, tts_voice, font_path, transparent_anchor_path):
    print(f"📱 Assembling {lang_name} Short...")
    audio_file = f"short_voice_{lang_name}.mp3"
    asyncio.run(_generate_voice_async(short_script, tts_voice, f"short_subs_{lang_name}.srt", audio_file))
    audio = AudioFileClip(audio_file)
    duration = min(audio.duration, 55)
    audio = audio.subclip(0, duration)

    bg = VideoFileClip("background_clip.mp4").resize(height=1920).crop(width=1080)
    bg = bg.loop(duration=duration) if bg.duration < duration else bg.subclip(0, duration)
    bg = bg.fx(colorx, 0.6)

    if transparent_anchor_path:
        anchor_raw = VideoFileClip(transparent_anchor_path).without_audio()
        anchor = anchor_raw.loop(duration=duration).set_position(("center", "bottom")).resize(height=500)
    else:
        anchor = ImageClip("my_photo.png").set_duration(duration).set_position(("center", "bottom")).resize(height=500)

    text_clip = TextClip("FUTURE INTELLIGENCE", fontsize=50, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(duration).set_position(("center", 0.1))

    final_video = CompositeVideoClip([bg, text_clip, anchor]).set_audio(audio)
    output_file = f"shorts_{lang_name}.mp4"
    final_video.write_videofile(output_file, codec="libx264", audio_codec="aac", fps=30, threads=4, preset="medium")
    os.remove(audio_file)
    return output_file

# --- 7. AUTO-THUMBNAIL GENERATOR ---
def generate_thumbnail(lang_name, top_headline, font_path):
    print(f"🖼️ Generating {lang_name} Thumbnail...")
    img = Image.new('RGB', (1280, 720), color=(10, 10, 10))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 500, 1280, 720], fill=(180, 0, 0))
    
    try:
        anchor = Image.open("my_photo.png").resize((400, 400))
        img.paste(anchor, (850, 50))
    except: pass
        
    font_title = ImageFont.truetype(font_path, 60)
    font_headline = ImageFont.truetype(font_path, 45)
    
    draw.text((20, 20), "BREAKING NEWS", fill="red", font=font_title)
    draw.text((20, 540), top_headline[:40] + "...", fill="white", font=font_headline)
    
    output_file = f"thumbnail_{lang_name}.jpg"
    img.save(output_file, quality=95)
    return output_file

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    has_music = fetch_background_music()
    fetch_background_video()
    transparent_anchor_path = prepare_anchor_video() # Will return None if anchor.mp4 is missing, triggering the photo zoom
    
    fresh_news = get_fresh_news()
    if not fresh_news:
        print("❌ No fresh news found in the last 24 hours. Exiting.")
        exit()

    for lang_name, lang_data in LANGUAGES.items():
        print(f"\n--- Processing {lang_name} Channel ---")
        font_path = get_system_font(lang_data["font"])
        raw_output = generate_content(fresh_news, lang_name, lang_data["gemini_lang"])
        
        if not raw_output:
            print(f"❌ Skipping {lang_name} due to API error.")
            continue
            
        try:
            parts = raw_output.split("[LONG_SCRIPT]")[1].split("[SHORT_SCRIPT]")
            long_script = parts[0].strip()
            parts = parts[1].split("[METADATA]")
            short_script = parts[0].strip()
            parts = parts[1].split("[TICKER_TEXT]")
            metadata = parts[0].strip()
            ticker_text = parts[1].strip()
        except Exception as e:
            print(f"❌ Error parsing Gemini output for {lang_name}: {e}")
            continue

        with open(f"youtube_metadata_{lang_name}.txt", "w", encoding='utf-8') as f: f.write(metadata)
            
        audio_file, srt_file = generate_and_validate_voice(long_script, lang_name, lang_data["gemini_lang"], lang_data["tts"], fresh_news)
        assemble_long_video(audio_file, ticker_text, lang_name, fresh_news, font_path, has_music, transparent_anchor_path)
        assemble_shorts(short_script, lang_name, lang_data["tts"], font_path, transparent_anchor_path)
        generate_thumbnail(lang_name, fresh_news[0], font_path)
        
    print("\n✅ ALL ASSETS GENERATED SUCCESSFULLY! READY FOR MANUAL UPLOAD.")
