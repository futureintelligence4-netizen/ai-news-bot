import os
import sys
import time
import requests
import xml.etree.ElementTree as ET
from gtts import gTTS
from moviepy.editor import ImageClip, AudioFileClip
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai

# =================.CONFIGURATION=================

# Set your Gemini API Key in your environment variables, or paste it here
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
genai.configure(api_key=GEMINI_API_KEY)

# Fixed: Using a valid model name to prevent 503 errors
GEMINI_MODEL = "gemini-2.0-flash" 

CHANNELS = {
    "FutureIntelligence": {
        "name": "Future Intelligence News",
        "topic": "artificial intelligence stocks OR tech business latest news",
        "language": "en"
    }
}

# =================COMPONENTS=================

def fetch_latest_news(topic):
    print(f"📰 Fetching latest news for: {topic}...")
    # Using Google News RSS for reliable, real-time news fetching
    url = f"https://news.google.com/rss/search?q={topic.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        item = root.find('.//item')
        
        if item is not None:
            title = item.find('title').text
            # Clean up HTML entities that sometimes appear in RSS titles
            title = title.replace("&#39;", "'").replace("&quot;", '"')
            return title
        return "AI Technology sees major breakthroughs in global markets"
    except Exception as e:
        print(f"⚠️ News fetch failed: {e}. Using fallback.")
        return "Latest updates in artificial intelligence and tech business"

def fetch_background_image(query):
    print("🖼️ Fetching relevant background images...")
    # Using LoremFlickr for a free, reliable stock photo without API keys
    img_url = f"https://loremflickr.com/1280/720/artificialintelligence,technology"
    
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
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 100))
        img.paste(overlay, (0, 0), overlay)
        
        # Load a default font
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()

        # Add text
        draw.text((50, 300), "FUTURE INTELLIGENCE", fill="red", font=font)
        draw.text((50, 360), news_title[:60] + "...", fill="white", font=font)
        
        img.save("thumbnail.jpg")
    except Exception as e:
        print(f"⚠️ Thumbnail generation warning: {e}")

def generate_script(news_title, channel_name):
    print(f"📝 Generating script for {channel_name}...")
    
    prompt = (
        f"Act as a professional YouTube news anchor. Write a short, 1-minute script "
        f"(about 120 words) reporting on this news headline: '{news_title}'. "
        f"Focus on the impact of AI and tech business. Do not include stage directions, "
        f"just the spoken text."
    )
    
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    # Retry mechanism to handle transient 503/500 API errors
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(3) # Wait 3 seconds before retrying
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

def upload_to_youtube(video_path, title):
    print("📤 Uploading to YouTube...")
    # NOTE: This is a simplified placeholder. Real YouTube uploads require OAuth2 
    # setup and the google-api-python-client. 
    print(f"✅ [SIMULATED UPLOAD] Video '{title}' would be uploaded from {video_path}.")
    # To implement real uploads, follow: https://developers.google.com/youtube/v3/quickstart/python

# =================MAIN EXECUTION=================

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
    generate_thumbnail(bg_image, news_title)
    
    # 4. Generate Script (Fixed API)
    script = generate_script(news_title, channel['name'])
    
    # 5. Generate Voiceover
    audio_file = generate_voiceover(script, channel['language'])
    
    # 6. Render Video
    video_file = render_video(bg_image, audio_file)
    
    # 7. Upload
    upload_to_youtube(video_file, news_title)
    
    print("✅ Done.\n")

if __name__ == "__main__":
    # Allow running without arguments (defaults to FutureIntelligence)
    # or pass a specific channel key if you add more later.
    target_channel = sys.argv[1] if len(sys.argv) > 1 else "FutureIntelligence"
    run_channel(target_channel)
