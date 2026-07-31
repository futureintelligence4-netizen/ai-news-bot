import os
import shutil
# --- MOVIEPY IMAGEMAGICK FIX ---
import moviepy.config as mp_config
if shutil.which("convert"):
    mp_config.change_settings({"IMAGEMAGICK_BINARY": shutil.which("convert")})

# --- PILLOW COMPATIBILITY PATCH (Fixes MoviePy ANTIALIAS error) ---
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'): PIL.Image.ANTIALIAS = PIL.Image.Resampling.LANCZOS

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
    TextClip, ColorClip, CompositeAudioClip, concatenate_videoclips
)
from moviepy.video.fx.all import colorx
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
LANGUAGES = {
    "English": {"tts": "en-IN-NeerjaNeural", "gemini_lang": "Indian English", "font": "Noto Sans Bold"}
}

BLOCKED_KEYWORDS = ["war", "dead", "death", "kill", "attack", "suicide", "terror", "blood", "gore", "shoot", "bomb", "tragedy", "casualt"]

# --- 0. DYNAMIC ASSET FETCHERS & UTILITIES ---
def get_system_font(font_name):
    try:
        result = subprocess.run(['fc-match', '-f', '%{file}', font_name], capture_output=True, text=True)
        if result.stdout and result.stdout.strip(): return result.stdout.strip()
    except Exception: pass
    return "Roboto-Bold.ttf"

def fetch_background_images(headlines):
    """Fetches a specific image for each news story to keep the video relevant and rendering fast."""
    print("🖼️ Fetching relevant background images for stories...")
    headers = {"Authorization": os.environ.get("PEXELS_API_KEY")}
    image_paths = []
    
    for i, headline in enumerate(headlines[:5]):
        search_query = " ".join(headline.split()[:3])
        try:
            r = requests.get(f"https://api.pexels.com/v1/search?query={search_query}&per_page=1", headers=headers, timeout=15)
            if r.status_code == 200 and r.json()['photos']:
                img_url = r.json()['photos'][0]['src']['large']
                img_data = requests.get(img_url).content
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
        if len(fresh_news) >= 5: break
            
    with open("news_history.json", "w") as f: json.dump(history, f, indent=4)
    return fresh_news

# --- 2. GEMINI RAW API CALL ---
def call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY").strip()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192}
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code != 200:
            print(f"🔍 Google API Raw Response: {response.text}")
        response.raise_for_status()
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"❌ Raw API call failed: {e}")
        return ""

def generate_content(headlines, language_name, gemini_lang):
    print(f"📝 Generating scripts & metadata for {language_name} via raw API...")
    ist_time = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    time_of_day = "morning" if ist_time.hour < 12 else "evening"
    current_date_str = ist_time.strftime("%A, %B %d, %Y")
    
    prompt = f"""
    You are a top-tier prime-time news anchor for 'Future Intelligence News' in India.
    Write a highly detailed 1,500+ word broadcast script in **{gemini_lang}** based on these latest headlines: {headlines}.
    Do NOT translate literally. Write natively as a local news channel would speak.
    
    FOLLOW THIS EXACT BROADCAST STRUCTURE:
    [INTRODUCTION] Welcome viewers. Mention today's exact date ({current_date_str}) and {time_of_day} broadcast.
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
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                try:
                    submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
                except Exception:
                    pass
    
    try:
        subs = submaker.generate_subs()
        with open(srt_path, "w", encoding='utf-8') as f:
            f.write(subs)
    except Exception as e:
        print(f"⚠️ Subtitle generation skipped: {e}")
        with open(srt_path, "w", encoding='utf-8') as f:
            f.write("1\n00:00:00,000 --> 00:00:10,000\nSubtitles temporarily unavailable\n")

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

# --- 5. PRO VIDEO ASSEMBLY (LONG FORM - FAST RENDER) ---
def assemble_long_video(audio_file, ticker_text, lang_name, headlines, font_path, image_paths):
    print(f"🎬 Assembling Long-form {lang_name} Broadcast (Fast Mode)...")
    audio = AudioFileClip(audio_file)
    duration = audio.duration

    num_imgs = len(image_paths)
    segment_duration = duration / num_imgs
    
    bg_clips = []
    for i, img_path in enumerate(image_paths):
        img_clip = ImageClip(img_path).set_duration(segment_duration).resize(height=1080).crop(width=1920)
        overlay = ColorClip(size=(1920, 1080), color=(0, 0, 0)).set_duration(segment_duration).set_opacity(0.5)
        bg_clips.append(CompositeVideoClip([img_clip, overlay]))
        
    bg = concatenate_videoclips(bg_clips)

    anchor = ImageClip("my_photo.png").set_duration(duration).set_position(("right", "top")).resize(height=350)

    logo = TextClip("FUTURE INTELLIGENCE NEWS", fontsize=36, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(duration).set_position((20, 20))
    live_dot = ColorClip(size=(20, 20), color=(220, 0, 0)).set_duration(duration).set_position((20, 70))
    live_text = TextClip("LIVE", fontsize=24, color='white', font=font_path, stroke_color='red', stroke_width=1).set_duration(duration).set_position((50, 68))
    
    ist_time = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    clock_str = ist_time.strftime("%H:%M:%S IST")
    clock = TextClip(clock_str, fontsize=22, color='white', font=font_path).set_duration(duration).set_position((20, 100))

    ticker_bg = ColorClip(size=(1920, 80), color=(180, 0, 0)).set_duration(duration).set_position(("center", "bottom"))
    ticker_label = TextClip("BREAKING", fontsize=36, color='black', font=font_path).set_duration(duration).set_position((10, 1010))
    ticker_clip = TextClip(ticker_text, fontsize=38, color='white', font=font_path).set_duration(duration).set_position(lambda t: (1920 - 40 * t, 1010))

    lower_thirds = []
    for i, hl in enumerate(headlines[:3]):
        start = int(i * segment_duration) + 10
        if start < duration:
            lt_bg = ColorClip(size=(1000, 60), color=(0, 0, 0)).set_duration(20).set_position((20, 850)).set_opacity(0.8).set_start(start)
            lt_text = TextClip(hl[:60] + "...", fontsize=28, color='yellow', font=font_path, stroke_color='black', stroke_width=1).set_duration(20).set_position((30, 855)).set_start(start)
            lower_thirds.extend([lt_bg, lt_text])

    final_video = CompositeVideoClip([bg, logo, live_dot, live_text, clock, anchor, ticker_bg, ticker_label, ticker_clip] + lower_thirds).set_audio(audio)
    
    output_file = f"final_news_{lang_name}.mp4"
    final_video.write_videofile(output_file, codec="libx264", audio_codec="aac", fps=24, threads=4, preset="ultrafast")
    os.remove(audio_file)
    return output_file

# --- 6. SHORTS ASSEMBLY ---
def assemble_shorts(short_script, lang_name, tts_voice, font_path, image_paths):
    print(f"📱 Assembling {lang_name} Short...")
    audio_file = f"short_voice_{lang_name}.mp3"
    asyncio.run(_generate_voice_async(short_script, tts_voice, f"short_subs_{lang_name}.srt", audio_file))
    audio = AudioFileClip(audio_file)
    duration = min(audio.duration, 55)
    audio = audio.subclip(0, duration)

    bg_img = ImageClip(image_paths[0]).set_duration(duration).resize(height=1920).crop(width=1080)
    overlay = ColorClip(size=(1080, 1920), color=(0, 0, 0)).set_duration(duration).set_opacity(0.6)
    bg = CompositeVideoClip([bg_img, overlay])

    anchor = ImageClip("my_photo.png").set_duration(duration).set_position(("center", "bottom")).resize(height=500)
    text_clip = TextClip("FUTURE INTELLIGENCE", fontsize=50, color='white', font=font_path, stroke_color='black', stroke_width=2).set_duration(duration).set_position(("center", 0.1))

    final_video = CompositeVideoClip([bg, text_clip, anchor]).set_audio(audio)
    output_file = f"shorts_{lang_name}.mp4"
    final_video.write_videofile(output_file, codec="libx264", audio_codec="aac", fps=24, threads=4, preset="ultrafast")
    os.remove(audio_file)
    return output_file

# --- 7. PRO AUTO-THUMBNAIL GENERATOR (NO ANCHOR PHOTO) ---
def generate_thumbnail(lang_name, top_headline, font_path, bg_image_path):
    print(f"🖼️ Generating Professional {lang_name} Thumbnail...")
    W, H = 1280, 720
    try:
        # Use the relevant news background image
        img = Image.open(bg_image_path).resize((W, H))
    except:
        img = Image.new('RGB', (W, H), color=(5, 5, 15))
        
    draw = ImageDraw.Draw(img, "RGBA")
    
    # Darken the background heavily so text pops
    draw.rectangle([0, 0, W, H], fill=(0, 0, 0, 160)) 
    
    # Red Breaking News Banner
    draw.rectangle([0, 0, W, 90], fill=(220, 0, 0, 255))
    font_banner = ImageFont.truetype(font_path, 50)
    draw.text((40, 15), "BREAKING NEWS", fill="white", font=font_banner)
    
    # Main Headline Text (wrapped)
    font_headline = ImageFont.truetype(font_path, 65)
    words = top_headline.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = (current_line + " " + word).strip()
        bbox = draw.textbbox((0,0), test_line, font=font_headline)
        if bbox[2] - bbox[0] <= 1150: 
            current_line = test_line
        else:
            if current_line: lines.append(current_line)
            current_line = word
    if current_line: lines.append(current_line)
    
    y = 250
    for line in lines[:4]:
        draw.text((42, y+2), line, fill=(0,0,0), font=font_headline)
        draw.text((40, y), line, fill="yellow", font=font_headline)
        y += 75
    
    # Bottom Banner
    draw.rectangle([0, 650, W, H], fill=(200, 0, 0, 255))
    font_channel = ImageFont.truetype(font_path, 35)
    draw.text((40, 665), "FUTURE INTELLIGENCE NEWS", fill="white", font=font_channel)
    
    output_file = f"thumbnail_{lang_name}.jpg"
    img.save(output_file, quality=95)
    return output_file

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    fresh_news = get_fresh_news()
    if not fresh_news:
        print("❌ No fresh news found in the last 24 hours. Exiting.")
        exit()

    image_paths = fetch_background_images(fresh_news)
    
    for lang_name, lang_data in LANGUAGES.items():
        print(f"\n--- Processing {lang_name} Channel ---")
        font_path = get_system_font(lang_data["font"])
        raw_output = generate_content(fresh_news, lang_name, lang_data["gemini_lang"])
        
        if not raw_output:
            print(f"❌ Skipping {lang_name} due to API error.")
            continue
            
        try:
            long_script = ""
            short_script = ""
            metadata = ""
            ticker_text = "Breaking News"
            
            if "[LONG_SCRIPT]" in raw_output:
                long_script = raw_output.split("[LONG_SCRIPT]")[1].split("[SHORT_SCRIPT]")[0].strip()
            if "[SHORT_SCRIPT]" in raw_output:
                short_script = raw_output.split("[SHORT_SCRIPT]")[1].split("[METADATA]")[0].strip()
            if "[METADATA]" in raw_output:
                metadata = raw_output.split("[METADATA]")[1].split("[TICKER_TEXT]")[0].strip()
            if "[TICKER_TEXT]" in raw_output:
                ticker_text = raw_output.split("[TICKER_TEXT]")[1].strip().split("\n")[0]
                
        except Exception as e:
            print(f"❌ Error parsing Gemini output for {lang_name}: {e}")
            continue

        with open(f"youtube_metadata_{lang_name}.txt", "w", encoding='utf-8') as f: f.write(metadata)
            
        audio_file, srt_file = generate_and_validate_voice(long_script, lang_name, lang_data["gemini_lang"], lang_data["tts"], fresh_news)
        assemble_long_video(audio_file, ticker_text, lang_name, fresh_news, font_path, image_paths)
        assemble_shorts(short_script, lang_name, lang_data["tts"], font_path, image_paths)
        
        # Pass the first news image to be used as the thumbnail background
        generate_thumbnail(lang_name, fresh_news[0], font_path, image_paths[0])
        
    print("\n✅ ALL ASSETS GENERATED SUCCESSFULLY! READY FOR MANUAL UPLOAD.")
