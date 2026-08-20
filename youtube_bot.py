import os
import sys
import time
import json
import asyncio
import requests
import xml.etree.ElementTree as ET
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip
from PIL import Image, ImageDraw, ImageFont

# Google API Libraries
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ================= CONFIGURATION =================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-pro" # Stable model that won't give 404 errors

CHANNELS = {
    "FutureIntelligence": {
        "name": "Future Intelligence News",
        "topic": "artificial intelligence stocks OR tech business latest news",
        "language": "en"
    }
}

# ================= COMPONENTS =================

def fetch_latest_news(topic):
    print(f"📰 Fetching latest news for: {topic}...")
    url = f"https://news.google.com/rss/search?q={topic.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        item = root.find('.//item')
        if item is not None:
            title = item.find('title').text
            title = title.replace("&#39;", "'").replace("&quot;", '"')
            return title
        return "AI Technology sees major breakthroughs in global markets"
    except Exception as e:
        print(f"⚠️ News fetch failed: {e}. Using fallback.")
        return "Latest updates in artificial intelligence and tech business"

def fetch_background_image(query):
    print("🖼️ Fetching relevant background images...")
    # Using Picsum (much more reliable than LoremFlickr)
    img_url = "https://picsum.photos/1080/1920"
    try:
        response = requests.get(img_url, stream=True, timeout=10)
        response.raise_for_status()
        with open("background.jpg", "wb") as f:
            f.write(response.content)
        return "background.jpg"
    except Exception as e:
        print(f"⚠️ Image fetch failed: {e}. Generating solid color background.")
        img = Image.new('RGB', (1080, 1920), color=(10, 20, 40))
        img.save("background.jpg")
        return "background.jpg"

def generate_thumbnail(image_path, news_title, channel_name):
    print("🖼️ Generating AI Thumbnail Background...")
    try:
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 120))
        img.paste(overlay, (0, 0), overlay)
        
        try:
            font_large = ImageFont.truetype("arial.ttf", 70)
            font_small = ImageFont.truetype("arial.ttf", 40)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        draw.text((50, 800), channel_name.upper(), fill="red", font=font_large)
        draw.text((50, 900), news_title[:50] + "...", fill="white", font=font_small)
        
        img.save("thumbnail.jpg")
        return "thumbnail.jpg"
    except Exception as e:
        print(f"⚠️ Thumbnail generation warning: {e}")
        return image_path

def generate_script(news_title, channel_name):
    print(f"📝 Generating script for {channel_name}...")
    prompt = (
        f"Act as a professional YouTube news anchor. Write a short, 1-minute script "
        f"(about 120 words) reporting on this news headline: '{news_title}'. "
        f"Focus on the impact of AI and tech business. Do not include stage directions, "
        f"just the spoken text."
    )
    model = genai.GenerativeModel(GEMINI_MODEL)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                print("❌ All API retries exhausted. Using fallback script.")
                return f"Welcome to Future Intelligence News. Our top story today: {news_title}. Experts are weighing in on what this means for the tech industry and global markets. Analysts suggest this development could lead to significant shifts in artificial intelligence applications and business strategies. Industry leaders are already responding to the news, pointing out both the challenges and opportunities that lie ahead. We will continue to monitor this breaking story and bring you more updates as they become available. Stay tuned for more in-depth coverage of the technology shaping our future."

def generate_voiceover(script_text, language="en"):
    print("🎙️ Generating fast, professional voiceover...")
    
    # Uses Microsoft Edge Neural Voice, talks 25% faster
    async def create_audio():
        communicate = edge_tts.Communicate(text=script_text, voice="en-US-GuyNeural", rate="+25%")
        await communicate.save("voiceover.mp3")
        
    asyncio.run(create_audio())
    return "voiceover.mp3"

def render_video(image_path, audio_path):
    print("🎬 Rendering video...")
    audio_clip = AudioFileClip(audio_path)
    video_clip = ImageClip(image_path).set_duration(audio_clip.duration).set_audio(audio_clip)
    video_clip = video_clip.set_fps(24)
    output_path = "final_video.mp4"
    video_clip.write_videofile(output_path, codec="libx264", audio_codec="aac", verbose=False, logger=None)
    return output_path

def upload_to_youtube(video_path, title, thumbnail_path):
    print("📤 Uploading to YouTube...")
    try:
        token_json = os.getenv("YOUTUBE_TOKEN")
        if not token_json:
            print("❌ YOUTUBE_TOKEN not found in secrets! Skipping upload.")
            return None
            
        token_data = json.loads(token_json)
        creds = Credentials(
            token=None,
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )
        creds.refresh(Request())
        youtube = build("youtube", "v3", credentials=creds)
        
        body = {
            "snippet": {
                "title": title[:100],
                "description": f"Breaking News: {title}\n\n#Shorts #News #Trending #AI",
                "tags": ["News", "Trending", "AI", "FutureIntelligence", "Shorts"],
                "categoryId": "28"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"⏳ Upload progress: {int(status.progress() * 100)}%")
                
        video_id = response['id']
        print(f"✅ Video uploaded successfully! URL: https://www.youtube.com/watch?v={video_id}")
        
        try:
            print("🖼️ Uploading custom thumbnail...")
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")).execute()
            print("✅ Thumbnail uploaded.")
        except Exception as thumb_e:
            print(f"⚠️ Thumbnail upload skipped: {thumb_e}")
            
        return video_id
    except Exception as e:
        print(f"❌ YouTube upload failed: {e}")
        return None

# ================= MAIN EXECUTION =================

def run_channel(channel_arg):
    channel = CHANNELS.get(channel_arg)
    if not channel:
        print(f"❌ Channel '{channel_arg}' not found. Defaulting to FutureIntelligence.")
        channel = CHANNELS["FutureIntelligence"]
        
    print(f"\n=== STARTING CHANNEL: {channel['name']} ===")
    
    news_title = fetch_latest_news(channel['topic'])
    bg_image = fetch_background_image(channel['topic'])
    thumbnail_path = generate_thumbnail(bg_image, news_title, channel['name'])
    script = generate_script(news_title, channel['name'])
    audio_file = generate_voiceover(script, channel['language'])
    video_file = render_video(bg_image, audio_file)
    
    upload_to_youtube(video_file, news_title, thumbnail_path)
    print("✅ Done.\n")

if __name__ == "__main__":
    run_channel("FutureIntelligence")
