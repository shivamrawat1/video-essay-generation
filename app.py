import os
import requests
import json
import re
import subprocess
from flask import Flask, render_template, request, send_file, redirect, url_for
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List
from gtts import gTTS
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# Load environment variables from the .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize OpenAI client
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

# Define the scene model
class Scene(BaseModel):
    scene_number: int
    explainer: str
    image_prompt: str

class BookScenes(BaseModel):
    book_title: str
    scenes: List[Scene]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/loading')
def loading():
    return render_template('loading.html')

@app.route('/download_video')
def download_video():
    video_path = request.args.get('video_path')

    # Serve the file for download using send_file
    return send_file(video_path, as_attachment=True, download_name='final_video.mp4')

@app.route('/generate', methods=['POST'])
def generate():
    # Get form data
    book_title = request.form.get('book_title')
    num_scenes = int(request.form.get('num_scenes'))

    # Redirect to loading page
    return redirect(url_for('loading', book_title=book_title, num_scenes=num_scenes))

from flask import Flask, render_template, request, send_file, redirect, url_for
import os

@app.route('/process_video', methods=['POST'])
def process_video():
    book_title = request.form.get('book_title')
    num_scenes = int(request.form.get('num_scenes'))

    # Generate scenes based on the book title and number of scenes
    book_scenes = generate_scenes(book_title, num_scenes)

    if book_scenes:
        # Generate images and audio for the scenes
        generate_and_save_images(book_scenes)
        generate_and_save_audio(book_scenes)

        # Create the final video and save it in 'static/generated_videos/'
        video_path = create_video(book_scenes, output_video="static/generated_videos/final_video.mp4")

        if video_path:
            # Redirect to a route that triggers the download
            return redirect(url_for('download_video', video_path=video_path))

    return "Failed to generate video."

def ensure_directory_exists(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"Directory '{directory_path}' created.")
    else:
        print(f"Directory '{directory_path}' already exists.")


def generate_scenes(book_title: str, num_scenes: int = 2) -> BookScenes:
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant and an amazing storyteller with the ability to break down books into explainers."},
            {"role": "user", "content": f"Divide the book '{book_title}' into {num_scenes} key scenes. For each scene, provide a summary (50-100 words of narration) and an image prompt describing the visual setting. Return the response in valid JSON format with 'scene_number', 'explainer', and 'image_prompt' as fields."}
        ]
    )

    generated_scenes = response.choices[0].message.content

    try:
        json_match = re.search(r'\{.*\}', generated_scenes, re.DOTALL)
        if json_match:
            json_content = json_match.group(0)
            parsed_scenes = json.loads(json_content)
        else:
            print("Error: No valid JSON found in the response.")
            return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None

    scenes_data = parsed_scenes.get("scenes", [])

    if scenes_data:
        scenes = []
        for idx, scene_data in enumerate(scenes_data):
            explainer = scene_data["explainer"]
            image_prompt = scene_data["image_prompt"]
            scene = Scene(
                scene_number=idx + 1,
                explainer=explainer,
                image_prompt=image_prompt
            )
            scenes.append(scene)

        return BookScenes(book_title=book_title, scenes=scenes)
    return None

def generate_and_save_images(book_scenes: BookScenes, output_folder: str = "scene_images"):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    prompts = [(scene.scene_number, scene.image_prompt) for scene in book_scenes.scenes]

    for scene_number, prompt in prompts:
        response = client.images.generate(
            prompt=prompt,
            n=1,
            size="1024x1024"
        )

        images_data = response.data

        for idx, image_data in enumerate(images_data):
            image_url = image_data.url
            img_data = requests.get(image_url).content
            image_filename = os.path.join(output_folder, f"scene_{scene_number}.png")
            with open(image_filename, 'wb') as image_file:
                image_file.write(img_data)
            print(f"Image saved as {image_filename}")

def generate_and_save_audio(book_scenes: BookScenes, audio_folder: str = "scene_audio"):
    if not os.path.exists(audio_folder):
        os.makedirs(audio_folder)

    for scene in book_scenes.scenes:
        explainer_text = scene.explainer
        scene_number = scene.scene_number
        tts = gTTS(text=explainer_text, lang='en')
        audio_filename = os.path.join(audio_folder, f"scene_{scene_number}.mp3")
        tts.save(audio_filename)
        print(f"Audio saved as {audio_filename}")

def create_video(book_scenes: BookScenes, output_video: str = "static/generated_videos/final_video.mp4", fps: int = 24):
    clips = []

    # Ensure the directory exists
    output_folder = os.path.dirname(output_video)
    ensure_directory_exists(output_folder)

    for scene in book_scenes.scenes:
        image_path = f"scene_images/scene_{scene.scene_number}.png"
        audio_path = f"scene_audio/scene_{scene.scene_number}.mp3"

        if os.path.exists(image_path) and os.path.exists(audio_path):
            image_clip = ImageClip(image_path, duration=AudioFileClip(audio_path).duration)
            audio_clip = AudioFileClip(audio_path)
            image_clip = image_clip.set_audio(audio_clip)
            image_clip = image_clip.set_fps(fps)
            clips.append(image_clip)
        else:
            print(f"Missing image or audio for scene {scene.scene_number}")

    if clips:
        final_clip = concatenate_videoclips(clips, method="compose")
        temp_video_path = "temp_video.mp4"
        final_clip.write_videofile(temp_video_path, fps=fps, audio_codec="aac")

        # Re-encode the video and save it in the correct folder
        reencoded_video_path = reencode_video(temp_video_path, output_video)
        return reencoded_video_path
    else:
        print("No clips were created, unable to generate video.")
        return None

def reencode_video(input_video: str, output_video: str) -> str:
    try:
        command = f"ffmpeg -i {input_video} -c:v libx264 -c:a aac -strict experimental {output_video}"
        subprocess.run(command, shell=True, check=True)
        print(f"Re-encoded video saved as {output_video}")
        return output_video
    except subprocess.CalledProcessError as e:
        print(f"Error during re-encoding: {e}")
        return None

if __name__ == '__main__':
    app.run(debug=True)
