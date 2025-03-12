from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import time
import os
import tkinter as tk
from tkinter import ttk
import threading
import urllib.parse
import re

def validate_url(url):
    pattern = r"https?://(www\.)?youtube\.com/playlist\?list=[\w-]+"
    return bool(re.match(pattern, url))

def extract_video_id(url):
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        video_id = query.get("v")
        if video_id:
            return video_id[0]
        match = re.search(r"watch\?v=([\w-]+)", url)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        print(f"Error extracting video ID from {url}: {e}")
        return None

def get_video_urls(playlist_url, max_videos=50, progress_callback=None):
    if not validate_url(playlist_url):
        raise ValueError(f"Invalid YouTube playlist URL: {playlist_url}")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    except WebDriverException as e:
        raise RuntimeError(f"Failed to initialize ChromeDriver: {e}")

    try:
        driver.get(playlist_url)
        time.sleep(3)

        max_scrolls = 100
        scroll_count = 0
        last_height = driver.execute_script("return document.documentElement.scrollHeight")
        while scroll_count < max_scrolls:
            driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.documentElement.scrollHeight")
            video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-playlist-video-renderer")
            if progress_callback:
                progress_callback(len(video_elements), max_videos, "Scrolling playlist...")
            if new_height == last_height or len(video_elements) >= max_videos:
                break
            last_height = new_height
            scroll_count += 1

        video_urls = []
        try:
            video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-playlist-video-renderer a#video-title")
        except NoSuchElementException:
            raise ValueError("Could not find video elements. YouTube DOM may have changed.")

        for i, element in enumerate(video_elements[:max_videos]):
            url = element.get_attribute("href")
            if url:
                video_id = extract_video_id(url)
                if video_id:
                    video_urls.append(f"https://www.youtube.com/watch?v={video_id}")
                    if progress_callback:
                        progress_callback(i + 1, len(video_elements[:max_videos]), f"Extracting URL {i + 1}/{min(len(video_elements), max_videos)}")

        if not video_urls:
            print("Warning: No video URLs found. The playlist may be empty or private.")

        return video_urls

    except Exception as e:
        print(f"Error during scraping: {e}")
        return []
    finally:
        driver.quit()

def extract_transcript(video_url, output_dir="transcripts"):
    """
    Extract transcript from a YouTube video and save it to a file.
    Args:
        video_url (str): URL of the YouTube video.
        output_dir (str): Directory to save the transcript (default: 'transcripts').
    Returns:
        bool: True if successful, False otherwise.
    """
    video_id = extract_video_id(video_url)
    if not video_id:
        print(f"Failed to extract video ID from {video_url}")
        return False

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        output_file = os.path.join(output_dir, f"{video_id}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            for entry in transcript:
                f.write(f"{entry['text']}\n")
        print(f"Transcript saved for {video_url} to {output_file}")
        return True
    except (TranscriptsDisabled, NoTranscriptFound) as e:
        print(f"Failed to extract transcript for {video_url}: {e}")
        return False
    except Exception as e:
        print(f"Error extracting transcript for {video_url}: {e}")
        return False

def save_urls_to_file(video_urls, filename="video_urls.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        for url in video_urls:
            f.write(f"{url}\n")
    print(f"Saved {len(video_urls)} URLs to {filename}")

class ProgressGUI:
    def __init__(self, root, total_steps, on_start):
        self.root = root
        self.total_steps = total_steps
        self.on_start = on_start
        self.root.title("YouTube Playlist Scraper Progress")

        self.progress_label = tk.Label(root, text="Starting...")
        self.progress_label.pack(pady=10)

        self.progress_bar = ttk.Progressbar(root, length=300, mode="determinate")
        self.progress_bar.pack(pady=10)

        self.start_button = tk.Button(root, text="Start Scraping", command=self.start_scraping)
        self.start_button.pack(pady=10)

    def update_progress(self, current, total, message):
        self.progress_bar["value"] = (current / total) * 100
        self.progress_label.config(text=message)
        self.root.update()

    def start_scraping(self):
        self.start_button.config(state="disabled")
        threading.Thread(target=self.on_start, daemon=True).start()

def main():
    playlist_url = "https://www.youtube.com/playlist?list=PLzJVLNWKVr6ksDjycE7NpSptOlcaEP-jQ"
    max_videos = 100

    def scrape_and_extract():
        try:
            video_urls = get_video_urls(playlist_url, max_videos, progress.update_progress)
            if video_urls:
                save_urls_to_file(video_urls, "video_urls.txt")
                progress.update_progress(max_videos, max_videos, "Finished scraping URLs! Extracting transcripts...")
                success_count = 0
                for i, url in enumerate(video_urls):
                    if extract_transcript(url, "transcripts"):
                        success_count += 1
                    progress.update_progress(i + 1, len(video_urls), f"Extracting transcript {i + 1}/{len(video_urls)} ({success_count} successful)")
                progress.update_progress(len(video_urls), len(video_urls), f"Finished extracting transcripts! {success_count}/{len(video_urls)} successful.")
            else:
                progress.update_progress(0, max_videos, "Failed to scrape URLs.")
        except Exception as e:
            progress.update_progress(0, max_videos, f"Error: {str(e)}")

    root = tk.Tk()
    progress = ProgressGUI(root, max_videos, scrape_and_extract)
    root.mainloop()

if __name__ == "__main__":
    main()