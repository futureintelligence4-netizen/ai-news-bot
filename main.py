import os
import asyncio
import random
import json
import glob
import subprocess
from datetime import datetime

import feedparser
import edge_tts
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip
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

VOICE = "en-US-GuyNeural" # Ultra-realistic Microsoft Edge voice
CHANNEL_NAME = "AI News Daily"
NUM_STORIES = 5           # Number of news stories per video
BACKGROUND_DIR = "."
FONT_PATH = "assets/Roboto-Bold.ttf"
INTRO_MUSIC = "assets/intro_music.mp3"
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

    # Pick 5 unique stories
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
# 2. TEXT-TO-SPEECH (Edge-TTS Natural Voice)
# ----------------------------------------------------------------------
async def generate_voiceover(text, filename):
    print("🎙️ Generating natural voiceover with edge-tts...")
    communicate = edge_tts.Communicate(text, voice=VOICE)
    await communicate.save(filename)
    print("✅ Voiceover saved.")

# ----------------------------------------------------------------------
# 3. CREATE OVERLAY GRAPHICS
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
    print(f"🎨 Creating news overlay for Story {story_num}...")
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

    # Red label changes for each story
    draw.rectangle([(40, banner_top + 30), (400, banner_top + 90)], fill=(220, 0, 0))
    draw.text((55, banner_top + 35), f"STORY {story_num}", fill=(255, 255, 255), font=font_label)

    wrapped = wrap_text(headline, font_title, W - 80)
    y = banner_top + 120
    for line in wrapped[:5]:
        draw.text((40, y), line, fill=(255, 255, 255), font=font_title)
        y += 65

    img.save(output_path)

# ----------------------------------------------------------------------
# 4. BUILD FINAL VIDEO (Multi-Story, Silent Video + Raw FFmpeg)
# ----------------------------------------------------------------------
def build_video(stories, voiceover_path, output_path="final_video.mp4"):
    print("🎬 Building silent video with MoviePy...")
    
    bg_files = glob.glob(os.path.join(BACKGROUND_DIR, "background*.mp4"))
    if not bg_files:
        raise Exception("No background videos found in assets/")
    bg_path = random.choice(bg_files)

    # Create an overlay image for each story
    overlay_clips = []
    for i, story in enumerate(stories):
        overlay_path = f"overlay_{i}.png"
        create_overlay(story["title"], i+1, overlay_path)
        
        # Each story gets an equal slice of time on screen (e.g., 120s / 5 = 24s each)
        # We use a large number (120s) because -shortest will cut it to the audio length later
        segment_duration = 120 / len(stories) 
        clip = ImageClip(overlay_path).set_duration(segment_duration).set_start(i * segment_duration)
        overlay_clips.append(clip)

    bg = VideoFileClip(bg_path).without_audio()
    bg = bg.crop(x_center=bg.w / 2, width=1080, height=1920)
    bg = bg.loop(duration=120).set_duration(120)

    final = CompositeVideoClip([bg] + overlay_clips, size=(1080, 1920)).set_duration(120)

    # Write SILENT video
    final.write_videofile(
        "silent_video.mp4",
        fps=24,
        codec="libx264",
        audio=False,
        threads=4,
        preset="ultrafast",
        ffmpeg_params=["-pix_fmt", "yuv420p"]
    )

    print("🎵 Merging audio and video using raw FFmpeg...")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_exe = "ffmpeg"

    if os.path.exists(INTRO_MUSIC) and os.path.getsize(INTRO_MUSIC) > 0:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", "silent_video.mp4",
            "-i", voiceover_path,
            "-i", INTRO_MUSIC,
            "-filter_complex", "[1:a]volume=1.0[a1];[2:a]volume=0.1[a2];[a1][a2]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", output_path
        ]
    else:
        cmd = [
            ffmpeg_exe, "-y",
            "-i", "silent_video.mp4",
            "-i", voiceover_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", output_path
        ]

    subprocess.run(cmd)

    # Cleanup
    for f in ["voice.mp3", "silent_video.mp4"] + [f"overlay_{i}.png" for i in range(len(stories))]:
        if os.path.exists(f):
            os.remove(f)

# ----------------------------------------------------------------------
# 5. UPLOAD TO YOUTUBE
# ----------------------------------------------------------------------
def upload_to_youtube(video_path, title, description, tags):
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

    print(f"✅ Uploaded! Video ID: {response['id']}")
    print(f"🔗 https://youtube.com/watch?v={response['id']}")
    return response["id"]

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Fetch 5 Stories
    stories = fetch_ai_news()
    
    # 2. Build Voiceover Script
    script = f"Here are the top {len(stories)} AI news stories today. "
    for i, story in enumerate(stories):
        script += f"Story number {i+1}. {story['title']}. {story['summary']} "
    script += f"That's all for today. Stay tuned to {CHANNEL_NAME} for more updates."
    
    voiceover_file = "voice.mp3"
    asyncio.run(generate_voiceover(script, voiceover_file))

    # 3. Build Video
    video_file = "final_video.mp4"
    build_video(stories, voiceover_file, video_file)

    # 4. Upload
    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    title = f"Top {len(stories)} AI News Stories - {date_str}"
    description = "In today's AI news:\n\n"
    for i, story in enumerate(stories):
        description += f"{i+1}. {story['title']}\n"
    description += f"\n🔔 Subscribe to {CHANNEL_NAME} for daily AI news updates.\n#AI #ArtificialIntelligence #MachineLearning #TechNews"

    tags = ["AI", "Artificial Intelligence", "AI News", "Machine Learning", "OpenAI", "Tech News"]

    upload_to_youtube(video_file, title, description, tags)

    if os.path.exists(video_file):
        os.remove(video_file)
    print("🎉 Done! Video live on YouTube.")
