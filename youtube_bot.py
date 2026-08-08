import os
import sys
import time
import requests
import xml.etree.ElementTree as ET
from gtts import gTTS
from moviepy.editor import ImageClip, AudioFileClip
from PIL import Image, ImageDraw, ImageFont

# Google API Libraries
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ================= CONFIGURATION =================

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE") # Replace with your Gemini key
genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.0-flash"

# YouTube API Configuration (Using Token 1)
YT_CLIENT_ID = "903336264135-lridj177v4k8d9r47nanps58lg0se9pn.apps.googleusercontent.com"
YT_CLIENT_SECRET = "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"
YT_REFRESH_TOKEN = "1//0gF0ciG-pzhIbCgYIARAAGBASNwF-L9Ir8AwnvUb7a7RjGYjqddTnWpLTRF_jCB_PYnmXL57SmcUXe_caF1tVQbi9omq64ZQgxpE"
YT_TOKEN_URI = "https://oauth2.googleapis.com/token"
YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Channel Configuration
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
    img_url = "https://loremflickr.com/1280/720/artificialintelligence,technology"
    
    try:
        response = requests.get(img_url, stream=True, timeout=10)
        response.raise_for_status()
        with open("background.jpg", "wb") as f:
            f.write(response.content)
        return "background.jpg"
    except Exception as e:
        print(f"⚠️ Image fetch failed: {e}. Generating solid color background.")
        img = Image.new('RGB', (1280, 720), color=(10, 20, 40))
        img.save("background.jpg")
        return "background.jpg"

def generate_thumbnail(image_path, news_title):
    print("🖼️ Generating AI Thumbnail Background...")
    try:
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        
        # Add a dark overlay so text is readable
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 120))
        img.paste(overlay, (0, 0), overlay)
        
        try:
            font_large = ImageFont.truetype("arial.ttf", 50)
            font_small = ImageFont.truetype("arial.ttf", 30)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        draw.text((50, 250), "FUTURE INTELLIGENCE", fill="red", font=font_large)
        draw.text((50, 320), news_title[:60] + "...", fill="white", font=font_small)
        
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
                return f"Breaking news today. {news_title}. We will continue to monitor this developing story."

def generate_voiceover(script_text, language="en"):
    print("🎙️ Generating voiceover...")
    tts = gTTS(text=script_text, lang=language, slow=False)
    tts.save("voiceover.mp3")
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
        # 1. Initialize Credentials and Refresh Token
        creds = Credentials(
            token=None,
            refresh_token=YT_REFRESH_TOKEN,
            token_uri=YT_TOKEN_URI,
            client_id=YT_CLIENT_ID,
            client_secret=YT_CLIENT_SECRET,
            scopes=YT_SCOPES
        )
        creds.refresh(Request()) # Automatically refreshes the access token
        
        # 2. Build YouTube API Service
        youtube = build("youtube", "v3", credentials=creds)
        
        # 3. Prepare Upload Body
        body = {
            "snippet": {
                "title": title[:100], # YouTube title limit is 100 characters
                "description": f"Breaking AI and Tech News: {title}\n\n#AI #TechNews #FutureIntelligence",
                "tags": ["AI", "Tech News", "Artificial Intelligence", "Future Intelligence"],
                "categoryId": "28" # Science & Technology
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        # 4. Execute Upload (Resumable Upload for stability)
        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"⏳ Upload progress: {int(status.progress() * 100)}%")
                
        video_id = response['id']
        print(f"✅ Video uploaded successfully! URL: https://www.youtube.com/watch?v={video_id}")
        
        # 5. Upload Custom Thumbnail (Requires YouTube Partner Program/Verification)
        try:
            print("🖼️ Uploading custom thumbnail...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            ).execute()
            print("✅ Thumbnail uploaded.")
        except Exception as thumb_e:
            print(f"⚠️ Thumbnail upload skipped (Channel may not be verified for custom thumbnails): {thumb_e}")
            
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
    
    # 1. Fetch News
    news_title = fetch_latest_news(channel['topic'])
    
    # 2. Fetch Image
    bg_image = fetch_background_image(channel['topic'])
    
    # 3. Generate Thumbnail
    thumbnail_path = generate_thumbnail(bg_image, news_title)
    
    # 4. Generate Script
    script = generate_script(news_title, channel['name'])
    
    # 5. Generate Voiceover
    audio_file = generate_voiceover(script, channel['language'])
    
    # 6. Render Video
    video_file = render_video(bg_image, audio_file)
    
    # 7. Upload to YouTube (Video + Thumbnail)
    upload_to_youtube(video_file, news_title, thumbnail_path)
    
    print("✅ Done.\n")

if __name__ == "__main__":
    target_channel = sys.argv[1] if len(sys.argv) > 1 else "FutureIntelligence"
    run_channel(target_channel)
