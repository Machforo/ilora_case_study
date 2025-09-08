# pre_check_in/media.py
import os
import requests

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")

def get_youtube_preview(video_url):
    """
    Try YouTube Data API to get best thumbnail + title. If API key missing,
    fallback to standard thumbnail URL.
    """
    try:
        if "youtu.be/" in video_url:
            vid = video_url.split("youtu.be/")[-1].split("?")[0]
        else:
            # parse v= parameter
            import urllib.parse as up
            q = up.urlparse(video_url).query
            params = up.parse_qs(q)
            vid = params.get("v", [None])[0]
        if not vid:
            return {"thumbnail": None, "title": None, "url": video_url}
        if YOUTUBE_API_KEY:
            api = "https://www.googleapis.com/youtube/v3/videos"
            params = {"part":"snippet","id":vid,"key":YOUTUBE_API_KEY}
            r = requests.get(api, params=params, timeout=8)
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    snip = items[0]["snippet"]
                    thumb = snip["thumbnails"].get("high", snip["thumbnails"].get("default"))["url"]
                    return {"thumbnail": thumb, "title": snip.get("title"), "url": video_url}
        # fallback thumbnail
        thumb = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        return {"thumbnail": thumb, "title": None, "url": video_url}
    except Exception:
        return {"thumbnail": None, "title": None, "url": video_url}

def get_instagram_preview(insta_url):
    """
    Instagram Basic Display or Graph API requires tokens and IDs. If token present,
    try to fetch media_id -> media_url. Otherwise return the original URL (Twilio/Streamlit will show it)
    """
    try:
        if INSTAGRAM_ACCESS_TOKEN:
            # naive attempt: call oembed as fallback (no token required for oembed)
            oembed = f"https://graph.facebook.com/v16.0/instagram_oembed?url={insta_url}"
            r = requests.get(oembed, timeout=8)
            if r.status_code == 200:
                data = r.json()
                return {"thumbnail": data.get("thumbnail_url"), "title": data.get("title") or "", "url": insta_url}
        # fallback: return URL only
        return {"thumbnail": None, "title": None, "url": insta_url}
    except Exception:
        return {"thumbnail": None, "title": None, "url": insta_url}
