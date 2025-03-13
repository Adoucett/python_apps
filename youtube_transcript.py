from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
import time
import os
import tkinter as tk
from tkinter import ttk, messagebox, StringVar
import threading
import urllib.parse
import re

def validate_youtube_url(url):
    pattern = r"https?://(www\.)?youtube\.com/(playlist\?list=[\w-]+|@?[\w-]+|channel/[\w-]+|c/[\w-]+|user/[\w-]+)"
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

def get_video_urls(url, max_videos=50, sort_option="newest", progress_callback=None):
    if not validate_youtube_url(url):
        raise ValueError(f"Invalid YouTube URL: {url}")
    
    options = webdriver.ChromeOptions()
    # For testing, we disable headless mode so you can see the browser. For production, uncomment the next line.
    # options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1200,800")
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    except WebDriverException as e:
        raise RuntimeError(f"Failed to initialize ChromeDriver: {e}")
    
    try:
        is_playlist = "playlist" in url
        if not is_playlist and ("/@" in url or "/c/" in url or "/user/" in url or "/channel/" in url):
            base_url = url.split("?")[0]
            if sort_option == "newest":
                url = f"{base_url}/videos?view=0&sort=dd&flow=grid"
            elif sort_option == "popular":
                url = f"{base_url}/videos?view=0&sort=p&flow=grid"
            elif sort_option == "oldest":
                url = f"{base_url}/videos?view=0&sort=da&flow=grid"
        
        if progress_callback:
            progress_callback(0, max_videos, f"Opening {url}...")
        
        driver.get(url)
        time.sleep(5)
        
        if is_playlist:
            selector = "ytd-playlist-video-renderer a#video-title"
        else:
            selector = "#video-title-link, a#video-title, ytd-grid-video-renderer a#video-title, ytd-rich-item-renderer a#video-title"
        
        video_urls = []
        previous_count = 0
        no_new_videos_count = 0
        max_retries = 5
        while len(video_urls) < max_videos and no_new_videos_count < max_retries:
            driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
            time.sleep(3)
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if not elements:
                    alternative_selectors = [
                        "a.ytd-grid-video-renderer", 
                        "a.ytd-rich-item-renderer",
                        "#content a.yt-simple-endpoint",
                        "ytd-grid-video-renderer h3 a"
                    ]
                    for alt_selector in alternative_selectors:
                        elements = driver.find_elements(By.CSS_SELECTOR, alt_selector)
                        if elements:
                            break
                
                current_urls = []
                for element in elements:
                    href = element.get_attribute("href")
                    if href and "watch?v=" in href:
                        video_id = extract_video_id(href)
                        if video_id:
                            current_urls.append(f"https://www.youtube.com/watch?v={video_id}")
                
                new_urls = [url for url in current_urls if url not in video_urls]
                video_urls.extend(new_urls)
                
                if progress_callback:
                    progress_callback(len(video_urls), max_videos, f"Found {len(video_urls)} videos...")
                
                if len(video_urls) == previous_count:
                    no_new_videos_count += 1
                    try:
                        show_more_button = driver.find_element(By.CSS_SELECTOR, "ytd-button-renderer.ytd-continuation-item-renderer")
                        driver.execute_script("arguments[0].click();", show_more_button)
                        time.sleep(3)
                        no_new_videos_count = 0
                    except Exception:
                        pass
                else:
                    no_new_videos_count = 0
                    
                previous_count = len(video_urls)
            except Exception as e:
                print(f"Error while scrolling: {e}")
                no_new_videos_count += 1
        
        video_urls = video_urls[:max_videos]
        
        if not video_urls:
            print("Warning: No video URLs found.")
        else:
            print(f"Successfully found {len(video_urls)} video URLs.")
        
        return video_urls
        
    except Exception as e:
        print(f"Error during scraping: {e}")
        return []
    finally:
        driver.quit()

def extract_transcript(video_url, output_dir="transcripts"):
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

class YouTubeScraperGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Transcript Scraper")
        self.root.geometry("700x600")
        self.root.resizable(False, False)
        
        header = tk.Label(root, text="YouTube Transcript Scraper", font=("Helvetica", 18, "bold"))
        header.pack(pady=10)
        
        # URL input
        input_frame = tk.Frame(root)
        input_frame.pack(pady=5, fill=tk.X, padx=20)
        
        tk.Label(input_frame, text="YouTube URL (playlist or channel):", font=("Helvetica", 12)).pack(anchor="w")
        self.url_entry = tk.Entry(input_frame, font=("Helvetica", 11))
        self.url_entry.pack(fill=tk.X, pady=5)
        tk.Label(input_frame, text="Examples: https://www.youtube.com/@ChannelName or a playlist URL", font=("Helvetica", 9), fg="gray").pack(anchor="w")
        
        # Sort option and max videos
        options_frame = tk.Frame(root)
        options_frame.pack(pady=5, fill=tk.X, padx=20)
        
        sort_frame = tk.Frame(options_frame)
        sort_frame.pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Label(sort_frame, text="Sort videos by:", font=("Helvetica", 12)).pack(anchor="w")
        self.sort_var = StringVar(value="newest")
        tk.Radiobutton(sort_frame, text="Newest", variable=self.sort_var, value="newest", font=("Helvetica", 10)).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(sort_frame, text="Popular", variable=self.sort_var, value="popular", font=("Helvetica", 10)).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(sort_frame, text="Oldest", variable=self.sort_var, value="oldest", font=("Helvetica", 10)).pack(side=tk.LEFT, padx=5)
        
        videos_frame = tk.Frame(options_frame)
        videos_frame.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        tk.Label(videos_frame, text="Max videos to scan:", font=("Helvetica", 12)).pack(anchor="w")
        self.max_videos_entry = tk.Entry(videos_frame, font=("Helvetica", 11))
        self.max_videos_entry.insert(0, "100")
        self.max_videos_entry.pack(fill=tk.X, pady=5)
        
        # Progress section
        progress_frame = tk.Frame(root)
        progress_frame.pack(pady=10, fill=tk.X, padx=20)
        self.progress_label = tk.Label(progress_frame, text="Waiting to start...", font=("Helvetica", 11))
        self.progress_label.pack(anchor="w")
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", length=650)
        self.progress_bar.pack(pady=5)
        
        # Status text area
        status_frame = tk.Frame(root)
        status_frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=20)
        tk.Label(status_frame, text="Status Log:", font=("Helvetica", 12, "bold")).pack(anchor="w")
        self.status_text = tk.Text(status_frame, height=12, font=("Helvetica", 10), wrap=tk.WORD)
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(status_frame, command=self.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.config(yscrollcommand=scrollbar.set)
        
        # Control buttons
        button_frame = tk.Frame(root)
        button_frame.pack(pady=15)
        self.start_button = tk.Button(button_frame, text="Start Scraping", command=self.start_scraping, font=("Helvetica", 12), width=15)
        self.start_button.pack(side=tk.LEFT, padx=10)
        self.exit_button = tk.Button(button_frame, text="Exit", command=root.destroy, font=("Helvetica", 12), width=15)
        self.exit_button.pack(side=tk.LEFT, padx=10)
    
    def _append_status(self, text):
        self.status_text.insert(tk.END, text)
        self.status_text.see(tk.END)
    
    def update_status(self, message):
        timestamp = time.strftime("%H:%M:%S")
        status_message = f"[{timestamp}] {message}\n"
        self.root.after(0, lambda: self._append_status(status_message))
    
    def update_progress(self, current, total, message):
        percent = (current / total) * 100 if total > 0 else 0
        def update():
            self.progress_bar["value"] = percent
            self.progress_label.config(text=message)
            self._append_status(message + "\n")
        self.root.after(0, update)
    
    def enable_start_button(self):
        self.root.after(0, lambda: self.start_button.config(state="normal"))
    
    def disable_start_button(self):
        self.root.after(0, lambda: self.start_button.config(state="disabled"))
    
    def start_scraping(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
            
        try:
            max_videos = int(self.max_videos_entry.get().strip())
            if max_videos <= 0:
                raise ValueError("Max videos must be a positive number")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for max videos")
            return
            
        sort_option = self.sort_var.get()
        self.disable_start_button()
        self.status_text.delete(1.0, tk.END)
        
        def scrape_process():
            try:
                self.update_status(f"Starting to scrape videos from: {url}")
                self.update_status(f"Sort option: {sort_option}")
                self.update_status(f"Looking for up to {max_videos} videos...")
                video_urls = get_video_urls(url, max_videos, sort_option, self.update_progress)
                
                if video_urls:
                    self.update_status(f"Successfully found {len(video_urls)} videos.")
                    save_urls_to_file(video_urls, "video_urls.txt")
                    self.update_status("Saved video URLs to video_urls.txt")
                    
                    self.update_progress(0, len(video_urls), f"Starting transcript extraction for {len(video_urls)} videos...")
                    success_count = 0
                    for i, video_url in enumerate(video_urls):
                        self.update_status(f"Processing {i+1}/{len(video_urls)}: {video_url}")
                        if extract_transcript(video_url, "transcripts"):
                            success_count += 1
                            self.update_status("✓ Successfully extracted transcript")
                        else:
                            self.update_status("✗ Failed to extract transcript")
                        self.update_progress(i + 1, len(video_urls), f"Processed {i + 1}/{len(video_urls)} videos ({success_count} successful)")
                    
                    self.update_progress(len(video_urls), len(video_urls), f"Finished! {success_count}/{len(video_urls)} transcripts extracted.")
                    self.update_status("Transcripts saved to the 'transcripts' folder")
                    self.root.after(0, lambda: messagebox.showinfo("Complete", f"Successfully extracted {success_count} out of {len(video_urls)} transcripts."))
                else:
                    self.update_progress(0, max_videos, "Failed to find any videos. Check the URL or try again.")
                    self.update_status("No videos were found. This could be due to:")
                    self.update_status("- The channel may not have public videos")
                    self.update_status("- YouTube may be blocking automated access")
                    self.update_status("- The page structure might have changed")
                    self.root.after(0, lambda: messagebox.showerror("Error", "No videos found. Please check the URL and try again."))
            except Exception as e:
                self.update_progress(0, max_videos, f"Error: {str(e)}")
                self.update_status(f"An error occurred: {str(e)}")
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.enable_start_button()
                
        threading.Thread(target=scrape_process, daemon=True).start()

def main():
    root = tk.Tk()
    app = YouTubeScraperGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
