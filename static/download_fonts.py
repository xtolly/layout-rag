import os
import re
import urllib.request

url = "https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        css_content = resp.read().decode('utf-8')
    
    font_urls = re.findall(r'url\((https://[^)]+)\)', css_content)
    font_dir = r"d:\Documents\Code\ai\layout-rag\static\fonts"
    os.makedirs(font_dir, exist_ok=True)
    
    for font_url in set(font_urls):
        filename = font_url.split("/")[-1]
        with urllib.request.urlopen(font_url) as font_resp:
            with open(os.path.join(font_dir, filename), "wb") as f:
                f.write(font_resp.read())
        
        css_content = css_content.replace(font_url, f"/static/fonts/{filename}")
    
    with open(r"d:\Documents\Code\ai\layout-rag\static\fonts.css", "w", encoding="utf-8") as f:
        f.write(css_content)
    
    print("SUCCESS: 字体下载完成，fonts.css 已生成到本地！")
except Exception as e:
    print(f"FAILED: {str(e)}")
