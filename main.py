import os
import asyncio
import random
import json
import glob
import subprocess
import urllib.parse
import requests
from datetime import datetime

import feedparser
import edge_tts
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, ColorClip
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=machine+learning+news&hl=en-US&gl=US&ceid=US:en",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
]

VOICE = "en-US-GuyNeural"
CHANNEL_NAME = "AI News Daily"
NUM_STORIES = 5
FONT_PATH = "Roboto-Bold.ttf"
INTRO_MUSIC = "intro_music.mp3"
SFX_TRANSITION = "sfx_whoosh.mp3"
ANCHOR_VIDEO = "anchor.mp4" 
USED_FILE = "used_articles.txt"

# ----------------------------------------------------------------------
# 1. FETCH AI NEWS & SCORE BY PRIORITY
# ----------------------------------------------------------------------
def score_article(article):
    score = 10
    text = (article['title'] + " " + article['summary']).lower()
    high_priority = ["openai", "chatgpt", "anthropic", "gemini", "google", "apple", "microsoft", "meta", "nvidia", "breakthrough", "billion", "funding", "launches", "gpt-4", "agi"]
    for kw in high_priority:
        if kw in text: score += 5
    med_priority = ["ai", "machine learning", "robot", "model", "tech", "data", "automation", "cybersecurity"]
    for kw in med_priority:
        if kw in text: score += 2
    if len(article['summary']) < 100: score -= 3
    return score

def fetch_ai_news():
    print(f"📰 Fetching AI news to find the top {NUM_STORIES} priority stories...")
    all_articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for article in feed.entries[:30]:
                title = article.title.strip()
                summary = ""
                if 'summary' in article: summary = article.summary.strip()
                elif 'description' in article: summary = article.description.strip()
                import re
                summary = re.sub(r'<[^>]+>', '', summary)
                if title and len(title) > 15:
                    all_articles.append({"title": title, "summary": summary})
        except Exception as e:
            print(f"⚠️ Failed to fetch {url}: {e}")

    used = load_used_articles()
    fresh = [a for a in all_articles if a["title"] not in used]
    if not fresh: fresh = all_articles

    for article in fresh: article['score'] = score_article(article)
    fresh.sort(key=lambda x: x['score'], reverse=True)

    num_to_select = min(NUM_STORIES, len(fresh))
    chosen = fresh[:num_to_select]
    
    for story in chosen: save_used_article(story["title"])
        
    print(f"✅ Selected Top {len(chosen)} Priority Stories!")
    for i, story in enumerate(chosen):
        print(f"   {i+1}. [Score: {story['score']}] {story['title']}")
    return chosen

def load_used_articles():
    if not os.path.exists(USED_FILE): return set()
    with open(USED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f.readlines()[-200:])

def save_used_article(title):
    with open(USED_FILE, "a", encoding="utf-8") as f: f.write(title + "\n")

# ----------------------------------------------------------------------
# 2. AI IMAGE GENERATION
# ----------------------------------------------------------------------
def generate_ai_image(headline, output_path):
    print(f"🖼️ Generating AI image for: {headline[:30]}...")
    prompt = f"{headline}, futuristic technology, artificial intelligence, digital art, cinematic lighting, 4k, no text"
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
    
    try:
        response = requests.get(url, timeout=45)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(response.content)
            print("✅ AI Image generated.")
            return True
        else:
            print(f"⚠️ Image generation failed (Status {response.status_code})")
            return False
    except Exception as e:
        print(f"⚠️ Image generation failed: {e}")
        return False

def format_image_vertical(input_path, output_path):
    try:
        img = Image.open(input_path).convert("RGB")
        width, height = img.size
        target_ratio = 1080 / 1920
        current_ratio = width / height

        if current_ratio > target_ratio:
            new_width = int(height * target_ratio)
            left = (width - new_width) / 2
            img = img.crop((left, 0, left + new_width, height))
        else:
            new_height = int(width / target_ratio)
            top = (height - new_height) / 2
            img = img.crop((0, top, width, top + new_height))

        img = img.resize((1080, 1920))
        img.save(output_path, "PNG")
        return True
    except Exception as e:
        print(f"⚠️ Image formatting failed: {e}")
        return False

# ----------------------------------------------------------------------
# 3. TEXT-TO-SPEECH & AUDIO ENGINE
# ----------------------------------------------------------------------
async def generate_story_audio(text, filename):
    print(f"🎙️ Generating voiceover for: {text[:40]}...")
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(filename)

def build_final_audio(num_stories):
    print("🎵 Stitching audio and sound effects together...")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    with open("audio_list.txt", "w") as f:
        for i in range(num_stories):
            f.write(f"file 'voice_{i}.mp3'\n")
            if i < num_stories - 1:
                if os.path.exists(SFX_TRANSITION): f.write(f"file '{SFX_TRANSITION}'\n")
    
    cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", "audio_list.txt", "-c:a", "libmp3lame", "-b:a", "48k", "voice.mp3"]
    subprocess.run(cmd)
    if os.path.exists("audio_list.txt"): os.remove("audio_list.txt")
    for i in range(num_stories):
        if os.path.exists(f"voice_{i}.mp3"): os.remove(f"voice_{i}.mp3")
    print("✅ Final voiceover with SFX created.")

# ----------------------------------------------------------------------
# 4. CREATE OVERLAY GRAPHICS, TICKER & THUMBNAIL
# ----------------------------------------------------------------------
def wrap_text(text, font, max_width):
    lines = []
    words = text.split()
    current_line = ""
    for word in words:
        test_line = (current_line + " " + word).strip()
        bbox = font.getbbox(test_line)
        width = bbox[2] - bbox[0]
        if width <= max_width: current_line = test_line
        else:
            if current_line: lines.append(current_line)
            current_line = word
    if current_line: lines.append(current_line)
    return lines

def create_overlay(headline, story_num, output_path="overlay.png"):
    print(f"🎨 Creating news overlay for News {story_num}...")
    W, H = 1080, 1920
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(FONT_PATH, 55)
        font_label = ImageFont.truetype(FONT_PATH, 40)
        font_channel = ImageFont.truetype(FONT_PATH, 32)
    except Exception:
        font_title = ImageFont.load_default()
        font_label = ImageFont.load_default()
        font_channel = ImageFont.load_default()

    draw.rectangle([(0, 0), (W, 110)], fill=(0, 0, 0, 220))
    draw.text((40, 35), f"🔴 LIVE  |  {CHANNEL_NAME}", fill=(255, 255, 255), font=font_channel)

    banner_top = 1400
    draw.rectangle([(0, banner_top), (W, 1820)], fill=(0, 0, 0, 200))

    draw.rectangle([(40, banner_top + 30), (380, banner_top + 90)], fill=(220, 0, 0))
    draw.text((55, banner_top + 35), f"NEWS {story_num}", fill=(255, 255, 255), font=font_label)

    wrapped = wrap_text(headline, font_title, W - 80)
    y = banner_top + 120
    for line in wrapped[:5]:
        draw.text((40, y), line, fill=(255, 255, 255), font=font_title)
        y += 65

    img.save(output_path)

def create_ticker_image(headlines, output_path="ticker.png"):
    print("🎟️ Creating scrolling ticker tape...")
    text_content = "   🔴 BREAKING AI NEWS   •   " + "   •   ".join(headlines) + "   •   SUBSCRIBE FOR MORE AI UPDATES DAILY   •   "
    try:
        font = ImageFont.truetype(FONT_PATH, 40)
    except Exception:
        font = ImageFont.load_default()
        
    bbox = font.getbbox(text_content)
    text_width = bbox[2] - bbox[0]
    W = text_width + 200
    H = 100
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W, H)], fill=(220, 0, 0, 255))
    draw.text((50, 25), text_content, fill=(255, 255, 255), font=font)
    img.save(output_path)

def create_thumbnail(stories, bg_image_path, output_path="thumbnail.jpg"):
    print("🖼️ Creating custom YouTube thumbnail...")
    W, H = 1280, 720
    try:
        img = Image.open(bg_image_path).resize((W, H))
    except:
        img = Image.new("RGB", (W, H), (10, 10, 20))
    
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([(0, 0), (W, H)], fill=(0, 0, 0, 120))

    try:
        font_huge = ImageFont.truetype(FONT_PATH, 70)
        font_med = ImageFont.truetype(FONT_PATH, 45)
    except Exception:
        font_huge = ImageFont.load_default()
        font_med = ImageFont.load_default()

    draw.rectangle([(0, 0), (W, 90)], fill=(220, 0, 0))
    draw.text((40, 20), f"🔴 LIVE  |  {CHANNEL_NAME}", fill=(255, 255, 255), font=font_med)

    y = 140
    for i in range(min(3, len(stories))):
        draw.rectangle([(40, y), (110, y+70)], fill=(220, 0, 0))
        draw.text((50, y+10), str(i+1), fill=(255, 255, 255), font=font_huge)
        wrapped = wrap_text(stories[i]["title"], font_med, W - 180)
        text_y = y + 10
        for line in wrapped[:2]:
            draw.text((130, text_y), line, fill=(255, 255, 0), font=font_med)
            text_y += 50
        y += 180

    img.save(output_path, "JPEG", quality=90)

# ----------------------------------------------------------------------
# 5. BULLETPROOF GREEN SCREEN ANCHOR
# ----------------------------------------------------------------------
def prepare_anchor_video():
    """Uses raw FFmpeg to remove green screen. Much more reliable than MoviePy."""
    if not os.path.exists(ANCHOR_VIDEO):
        print("⚠️ anchor.mp4 not found.")
        return None

    print("🟢 Removing green screen from anchor using raw FFmpeg...")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    output_path = "anchor_transparent.mp4"
    
    # FFmpeg chroma key command. We scale it to 400px wide, loop it, and make green transparent.
    cmd = [
        ffmpeg_exe, "-y",
        "-i", ANCHOR_VIDEO,
        "-t", "120",  # Limit to 120 seconds
        "-vf", "scale=400:-1,format=yuva420p,colorkey=0x00FF00:0.3:0.2",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ Anchor green screen removed successfully!")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"⚠️ FFmpeg failed to process anchor: {e}")
        return None

# ----------------------------------------------------------------------
# 6. BUILD FINAL VIDEO
# ----------------------------------------------------------------------
def build_video(stories, voiceover_path, output_path="final_video.mp4"):
    print("🎬 Building silent video with MoviePy...")
    
    segment_duration = 120 / len(stories)
    bg_clips = []
    overlay_clips = []
    
    for i, story in enumerate(stories):
        raw_img_path = f"raw_bg_{i}.png"
        vert_img_path = f"bg_{i}.png"
        
        if generate_ai_image(story["title"], raw_img_path):
            format_image_vertical(raw_img_path, vert_img_path)
            if os.path.exists(raw_img_path): os.remove(raw_img_path)
        else:
            vert_img_path = None 
            
        if vert_img_path:
            bg_segment = ImageClip(vert_img_path).set_duration(segment_duration).set_start(i * segment_duration)
        else:
            print(f"⚠️ Using solid color fallback for News {i+1}")
            bg_segment = ColorClip(size=(1080, 1920), color=(15, 15, 25), duration=segment_duration).set_start(i * segment_duration)
            
        bg_clips.append(bg_segment)
        
        overlay_path = f"overlay_{i}.png"
        create_overlay(story["title"], i+1, overlay_path)
        clip_duration = segment_duration + 1.0 if i < len(stories) - 1 else segment_duration
        clip = ImageClip(overlay_path).set_duration(clip_duration).set_start(i * segment_duration)
        if i > 0: clip = clip.crossfadein(1.0)
        overlay_clips.append(clip)

    final_clips = bg_clips + overlay_clips

    # 1. Scrolling Ticker Tape
    headlines = [s["title"] for s in stories]
    create_ticker_image(headlines, "ticker.png")
    ticker_img = ImageClip("ticker.png").set_duration(120)
    scroll_speed = (ticker_img.w + 1080) / 20.0 
    ticker_clip = ticker_img.set_position(lambda t: (1080 - (t * scroll_speed) % (ticker_img.w + 1080), 1820)).set_duration(120)
    final_clips.append(ticker_clip)

    # 2. Add Pre-processed Green Screen Anchor
    transparent_anchor_path = prepare_anchor_video()
    if transparent_anchor_path:
        print("👤 Loading transparent anchor into video...")
        try:
            anchor = VideoFileClip(transparent_anchor_path).without_audio()
            if anchor.duration < 120:
                anchor = anchor.loop(duration=120).set_duration(120)
            anchor_clip = anchor.set_position((640, 150)).set_duration(120)
            final_clips.append(anchor_clip)
            print("✅ Anchor added to scene!")
        except Exception as e:
            print(f"⚠️ Failed to load transparent anchor into MoviePy: {e}")

    final = CompositeVideoClip(final_clips, size=(1080, 1920)).set_duration(120)

    final.write_videofile(
        "silent_video.mp4",
        fps=24,
        codec="libx264",
        audio=False,
        threads=4,
        preset="ultrafast",
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )

    print("🎵 Merging final audio and video using raw FFmpeg...")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    merge_success = False
    if os.path.exists(INTRO_MUSIC) and os.path.getsize(INTRO_MUSIC) > 0:
        cmd_with_music = [
            ffmpeg_exe, "-y", "-i", "silent_video.mp4", "-i", voiceover_path, "-i", INTRO_MUSIC,
            "-filter_complex", "[1:a]volume=1.0[a1];[2:a]volume=0.1[a2];[a1][a2]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-shortest", output_path
        ]
        subprocess.run(cmd_with_music)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0: merge_success = True
        else: print("⚠️ Music file is corrupted! Falling back to voice only...")

    if not merge_success:
        cmd_voice_only = [ffmpeg_exe, "-y", "-i", "silent_video.mp4", "-i", voiceover_path, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", output_path]
        subprocess.run(cmd_voice_only)

    for f in ["voice.mp3", "silent_video.mp4", "ticker.png", "anchor_transparent.mp4"] + [f"overlay_{i}.png" for i in range(len(stories))] + [f"bg_{i}.png" for i in range(len(stories))]:
        if os.path.exists(f): os.remove(f)

# ----------------------------------------------------------------------
# 7. UPLOAD TO YOUTUBE
# ----------------------------------------------------------------------
def upload_to_youtube(video_path, thumb_path, title, description, tags):
    print("📤 Uploading to YouTube...")
    token_json = os.environ.get("YOUTUBE_TOKEN")
    if not token_json:
        if os.path.exists("token.json"):
            with open("token.json", "r") as f: token_json = f.read()
        else: raise Exception("YOUTUBE_TOKEN env var or token.json missing")

    token_data = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(token_data)
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

    video_id = response['id']
    print(f"✅ Uploaded! Video ID: {video_id}")
    print(f"🔗 https://youtube.com/watch?v={video_id}")

    if os.path.exists(thumb_path):
        print("🖼️ Uploading custom thumbnail...")
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumb_path)).execute()
            print("✅ Thumbnail uploaded successfully!")
        except Exception as e:
            print(f"⚠️ Thumbnail upload failed: {e}")
    return video_id

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    stories = fetch_ai_news()
    
    for i, story in enumerate(stories):
        script = f"News number {i+1}. {story['title']}. {story['summary']} "
        asyncio.run(generate_story_audio(script, f"voice_{i}.mp3"))
    build_final_audio(len(stories))

    thumb_bg_raw = "thumb_bg_raw.png"
    thumb_bg_vert = "bg_0.png" 
    if not os.path.exists(thumb_bg_vert):
        if generate_ai_image(stories[0]["title"], thumb_bg_raw):
            format_image_vertical(thumb_bg_raw, thumb_bg_vert)
            if os.path.exists(thumb_bg_raw): os.remove(thumb_bg_raw)

    thumb_file = "thumbnail.jpg"
    create_thumbnail(stories, thumb_bg_vert, thumb_file)

    video_file = "final_video.mp4"
    build_video(stories, "voice.mp3", video_file)

    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"Top {len(stories)} AI News Stories - {date_str}"
    description = "In today's AI news:\n\n"
    for i, story in enumerate(stories): description += f"{i+1}. {story['title']}\n"
    description += f"\n🔔 Subscribe to {CHANNEL_NAME} for daily AI news updates.\n#AI #ArtificialIntelligence #MachineLearning #TechNews"

    tags = ["AI", "Artificial Intelligence", "AI News", "Machine Learning", "OpenAI", "Tech News"]

    upload_to_youtube(video_file, thumb_file, title, description, tags)

    for f in [video_file, thumb_file]:
        if os.path.exists(f): os.remove(f)
    print("🎉 Done! Video live on YouTube.")
