import os
import sys
import json
import urllib.request
import urllib.error

def load_env():
    """Đọc file .env thủ công để tránh dependency python-dotenv"""
    env_vars = {}
    try:
        with open(".env", "rb") as f:
            content = f.read().decode("utf-8").strip()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return env_vars

def monitor_critique(code_to_check):
    env = load_env()
    api_key = os.getenv("GROQ_API_KEY") or env.get("GROQ_API_KEY")

    if not api_key:
        return "ERROR: Missing GROQ_API_KEY in environment or .env file."

    try:
        with open("docs/monitor_agent.md", "r", encoding="utf-8") as f:
            rules = f.read()
    except:
        rules = "Check logic and consistency."

    prompt = f"BẠN LÀ AGENT GIÁM SÁT ĐỘC LẬP.\nBỘ QUY TẮC:\n{rules}\n\nCODE:\n{code_to_check}\n\nYÊU CẦU: Bullet points ngắn gọn. Kết luận PASS hoặc FAIL."

    url = "https://api.groq.com/openai/v1/chat/completions"
    data = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    # Fix Cloudflare 403 block: Python urllib bị chặn vì User-Agent mặc định
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return f"HTTP Error {e.code}: {body[:300]}"
    except Exception as e:
        return f"ERROR: {str(e)}"

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        
    if len(sys.argv) < 2:
        code = sys.stdin.read()
    else:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            code = f.read()

    print("\n--- MONITOR AGENT CRITIQUE ---")
    print(monitor_critique(code))
    print("------------------------------\n")
