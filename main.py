import os
import asyncio
import random
import json
import glob
import subprocess
from datetime import datetime

import feedparser
import edge_tts
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, ColorClip, vfx
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
USED_FILE = "used_articles.txt"

# ----------------------------------------------------------------------
# 1. FETCH AI NEWS
# ----------------------------------------------------------------------
def fetch_ai_news():
    print(f"📰 Fetching AI news to find {NUM_STORIES} stories...")
    all_articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for article in feed.entries[:20]:
                title = article.title.strip()
                summary = ""
                if 'summary' in article:
                    summary = article.summary.strip()
                elif 'description' in article:
                    summary = article.description.strip()
                import re
                summary = re.sub(r'<[^>]+>', '', summary)
                if title and len(title) > 15:
                    all_articles.append({"title": title, "summary": summary})
        except Exception as e:
            print(f"⚠️ Failed to fetch {url}: {e}")

    used = load_used_articles()
    fresh = [a for a in all_articles if a["title"] not in used]
    if not fresh:
        fresh = all_articles

    num_to_select = min(NUM_STORIES, len(fresh))
    chosen = random.sample(fresh, num_to_select)
    
    for story in chosen:
        save_used_article(story["title"])
        
    print(f"✅ Selected {len(chosen)} stories!")
    for i, story in enumerate(chosen):
        print(f"   {i+1}. {story['title']}")
    return chosen

def load_used_articles():
    if not os.path.exists(USED_FILE):
        return set()
    with open(USED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f.readlines()[-200:])

def save_used_article(title):
    with open(USED_FILE, "a", encoding="utf-8") as f:
        f.write(title + "\n")

# ----------------------------------------------------------------------
# 2. TEXT-TO-SPEECH & AUDIO ENGINE
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
                if os.path.exists(SFX_TRANSITION):
                    f.write(f"file '{SFX_TRANSITION}'\n")
    
    cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", "audio_list.txt", "-c:a", "libmp3lame", "-b:a", "48k", "voice.mp3"]
    subprocess.run(cmd)
    
    if os.path.exists("audio_list.txt"): os.remove("audio_list.txt")
    for i in range(num_stories):
        if os.path.exists(f"voice_{i}.mp3"): os.remove(f"voice_{i}.mp3")
    print("✅ Final voiceover with SFX created.")

# ----------------------------------------------------------------------
# 3. CREATE OVERLAY GRAPHICS & THUMBNAIL
# ----------------------------------------------------------------------
def wrap_text(text, font, max_width):
    lines = []
    words = text.split()
    current_line = ""
    for word in words:
        test_line = (current_line + " " + word).strip()
        bbox = font.getbbox(test_line)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
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

    banner_top = 1480
    draw.rectangle([(0, banner_top), (W, H)], fill=(0, 0, 0, 200))

    draw.rectangle([(40, banner_top + 30), (380, banner_top + 90)], fill=(220, 0, 0))
    draw.text((55, banner_top + 35), f"NEWS {story_num}", fill=(255, 255, 255), font=font_label)

    wrapped = wrap_text(headline, font_title, W - 80)
    y = banner_top + 120
    for line in wrapped[:5]:
        draw.text((40, y), line, fill=(255, 255, 255), font=font_title)
        y += 65

    img.save(output_path)

def create_thumbnail(stories, output_path="thumbnail.jpg"):
    print("🖼️ Creating custom YouTube thumbnail...")
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), (10, 10, 20)) # Dark background
    draw = ImageDraw.Draw(img)

    try:
        font_huge = ImageFont.truetype(FONT_PATH, 70)
        font_med = ImageFont.truetype(FONT_PATH, 45)
        font_small = ImageFont.truetype(FONT_PATH, 35)
    except Exception:
        font_huge = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Top Red Banner
    draw.rectangle([(0, 0), (W, 90)], fill=(220, 0, 0))
    draw.text((40, 20), f"🔴 LIVE  |  {CHANNEL_NAME}", fill=(255, 255, 255), font=font_med)

    # Top 3 Headlines
    y = 140
    for i in range(min(3, len(stories))):
        # News Number Badge
        draw.rectangle([(40, y), (110, y+70)], fill=(220, 0, 0))
        draw.text((50, y+10), str(i+1), fill=(255, 255, 255), font=font_huge)
        
        # Headline Text (Yellow for clickability)
        wrapped = wrap_text(stories[i]["title"], font_med, W - 180)
        text_y = y + 10
        for line in wrapped[:2]: # Max 2 lines per headline
            draw.text((130, text_y), line, fill=(255, 255, 0), font=font_med)
            text_y += 50
        y += 180

    img.save(output_path, "JPEG", quality=90)
    print("✅ Thumbnail saved.")

# ----------------------------------------------------------------------
# 4. BUILD FINAL VIDEO (WITH PPT CROSSFADE EFFECT)
# ----------------------------------------------------------------------
def build_video(stories, voiceover_path, output_path="final_video.mp4"):
    print("🎬 Building silent video with MoviePy...")
    
    bg_files = glob.glob("*.mp4") + glob.glob("assets/*.mp4")
    
    try:
        if bg_files:
            bg_path = random.choice(bg_files)
            print(f"🎥 Using background video: {bg_path}")
            bg = VideoFileClip(bg_path).without_audio()
            bg = bg.crop(x_center=bg.w / 2, width=1080, height=1920)
            bg = bg.loop(duration=120).set_duration(120)
        else:
            raise Exception("No video file found")
    except Exception as e:
        print(f"⚠️ Background video missing or corrupted. Using solid color background. Error: {e}")
        bg = ColorClip(size=(1080, 1920), color=(15, 15, 25), duration=120)

    overlay_clips = []
    segment_duration = 120 / len(stories)
    
    for i, story in enumerate(stories):
        overlay_path = f"overlay_{i}.png"
        create_overlay(story["title"], i+1, overlay_path)
        
        # To crossfade, the clip needs to overlap the previous one by 1 second
        clip_duration = segment_duration + 1.0 if i < len(stories) - 1 else segment_duration
        clip = ImageClip(overlay_path).set_duration(clip_duration).set_start(i * segment_duration)
        
        # Add the PPT Crossfade effect (1 second smooth dissolve) for all stories after the first one
        if i > 0:
            clip = clip.crossfadein(1.0)
            
        overlay_clips.append(clip)

    final = CompositeVideoClip([bg] + overlay_clips, size=(1080, 1920)).set_duration(120)

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
            ffmpeg_exe, "-y",
            "-i", "silent_video.mp4",
            "-i", voiceover_path,
            "-i", INTRO_MUSIC,
            "-filter_complex", "[1:a]volume=1.0[a1];[2:a]volume=0.1[a2];[a1][a2]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", output_path
        ]
        subprocess.run(cmd_with_music)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            merge_success = True
        else:
            print("⚠️ Music file is corrupted! Falling back to voice only...")

    if not merge_success:
        cmd_voice_only = [
            ffmpeg_exe, "-y",
            "-i", "silent_video.mp4",
            "-i", voiceover_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", output_path
        ]
        subprocess.run(cmd_voice_only)

    for f in ["voice.mp3", "silent_video.mp4"] + [f"overlay_{i}.png" for i in range(len(stories))]:
        if os.path.exists(f):
            os.remove(f)

# ----------------------------------------------------------------------
# 5. UPLOAD TO YOUTUBE (WITH THUMBNAIL)
# ----------------------------------------------------------------------
def upload_to_youtube(video_path, thumb_path, title, description, tags):
    print("📤 Uploading to YouTube...")
    token_json = os.environ.get("YOUTUBE_TOKEN")
    if not token_json:
        if os.path.exists("token.json"):
            with open("token.json", "r") as f:
                token_json = f.read()
        else:
            raise Exception("YOUTUBE_TOKEN env var or token.json missing")

    token_data = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(token_data)

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
    print(f"✅ Uploaded! Video ID: {video_id}")
    print(f"🔗 https://youtube.com/watch?v={video_id}")

    if os.path.exists(thumb_path):
        print("🖼️ Uploading custom thumbnail...")
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path)
            ).execute()
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

    thumb_file = "thumbnail.jpg"
    create_thumbnail(stories, thumb_file)

    video_file = "final_video.mp4"
    build_video(stories, "voice.mp3", video_file)

    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"Top {len(stories)} AI News Stories - {date_str}"
    description = "In today's AI news:\n\n"
    for i, story in enumerate(stories):
        description += f"{i+1}. {story['title']}\n"
    description += f"\n🔔 Subscribe to {CHANNEL_NAME} for daily AI news updates.\n#AI #ArtificialIntelligence #MachineLearning #TechNews"

    tags = ["AI", "Artificial Intelligence", "AI News", "Machine Learning", "OpenAI", "Tech News"]

    upload_to_youtube(video_file, thumb_file, title, description, tags)

    for f in [video_file, thumb_file]:
        if os.path.exists(f):
            os.remove(f)
    print("🎉 Done! Video live on YouTube.")
