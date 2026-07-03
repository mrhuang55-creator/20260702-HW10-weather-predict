import os
import sys

# 強制將輸出設為 UTF-8 以防 Windows cp950 編碼出錯
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import re
import subprocess
import time
import py_compile
import urllib.request
import json

def log_info(msg):
    print(f"\033[32m[INFO] {msg}\033[0m")

def log_warn(msg):
    print(f"\033[33m[WARN] {msg}\033[0m")

def log_error(msg):
    print(f"\033[31m[ERROR] {msg}\033[0m")

def run_compile_check():
    log_info("正在進行 Python 語法靜態編譯檢查...")
    files_to_check = ['app.py', 'weather.py', 'ai_helper.py']
    for file in files_to_check:
        if not os.path.exists(file):
            log_error(f"檔案不存在: {file}")
            sys.exit(1)
        try:
            py_compile.compile(file, doraise=True)
            log_info(f"  - {file} 編譯成功")
        except py_compile.PyCompileError as e:
            log_error(f"  - {file} 編譯失敗! 語法錯誤:\n{e}")
            sys.exit(1)

def run_dom_check():
    log_info("正在進行 templates/index.html 核心 DOM 結構檢查...")
    html_path = os.path.join('templates', 'index.html')
    if not os.path.exists(html_path):
        log_error(f"HTML 模板不存在: {html_path}")
        sys.exit(1)
    
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_ids = ['windyIframe', 'tempChart', 'forecastContainer', 'countySelect', 'btnSyncAll']
    for rid in required_ids:
        # 簡單匹配 id="..."
        if f'id="{rid}"' not in content and f"id='{rid}'" not in content:
            log_error(f"  - 核心 ID 元件遺失: {rid} (請確認 templates/index.html 中是否有 id=\"{rid}\")")
            sys.exit(1)
        log_info(f"  - 檢驗通過: 元件 ID '{rid}' 存在")

def run_leakage_check():
    log_info("正在進行敏感 API 金鑰洩漏預防檢查...")
    
    # 金鑰匹配 Regex
    patterns = {
        'OpenAI API Key': re.compile(r'sk-[A-Za-z0-9]{32,}'),
        'Gemini API Key': re.compile(r'AIzaSy[A-Za-z0-9_-]{33}'),
        'CWA API Key': re.compile(r'CWA-[A-Za-z0-9-]{32,}')
    }
    
    # 掃描副檔名為 .py, .env, .json, .html 的檔案，排除 venv, logs, weather.db, env.private 等
    exclude_dirs = {'venv', '.venv', '.git', 'logs', '__pycache__'}
    exclude_files = {'env.private', 'weather.db'}
    
    leaks_found = 0
    
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file in exclude_files:
                continue
            
            ext = os.path.splitext(file)[1]
            if ext not in ['.py', '.env', '.json', '.html']:
                continue
                
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()
                
                for key_name, pattern in patterns.items():
                    matches = pattern.findall(file_content)
                    for m in matches:
                        # 排除佔位符和變數名
                        if "YOUR_" in m or "YOUR_CWA" in m or "YOUR_OPENAI" in m:
                            continue
                        log_error(f"  - [洩漏警告] 於 {file_path} 偵測到明文的 {key_name}: '{m[:6]}...{m[-4:]}'！")
                        leaks_found += 1
            except Exception as e:
                log_warn(f"無法讀取檔案進行掃描 {file_path}: {e}")
                
    if leaks_found > 0:
        log_error("❌ 推播攔截：發現明文 API 金鑰洩漏風險，請將金鑰移入 env.private 中！")
        sys.exit(1)
    else:
        log_info("  - 金鑰安全檢查通過：未發現明文金鑰洩漏")

def run_dynamic_server_check():
    log_info("正在啟動臨時本地測試伺服器以驗證 API 路由動態響應...")
    port = 5055
    
    # 設定環境變數
    test_env = os.environ.copy()
    test_env['PORT'] = str(port)
    test_env['FLASK_DEBUG'] = 'False'
    
    # 啟動子進程
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, 'app.py'],
            env=test_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 等待 2.5 秒啟動
        time.sleep(2.5)
        
        # 檢查子進程是否崩潰
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            log_error(f"伺服器啟動失敗，錯誤資訊:\n{stderr.decode('utf-8', errors='replace')}")
            sys.exit(1)
            
        # 測試首頁 GET
        log_info("  - 測試首頁路由 GET / ...")
        res_root = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
        if res_root.getcode() == 200:
            html = res_root.read().decode('utf-8')
            if 'tempChart' in html and 'windyIframe' in html:
                log_info("    [SUCCESS] 首頁響應正常，且已包含 Windy 與 Chart.js 核心元件！")
            else:
                log_error("    [FAIL] 首頁響應成功，但缺少關鍵網頁元件！")
                sys.exit(1)
        else:
            log_error(f"    [FAIL] 首頁返回非 200 狀態碼: {res_root.getcode()}")
            sys.exit(1)
            
        # 測試縣市 API GET
        log_info("  - 測試 API 路由 GET /api/counties ...")
        res_api = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/counties", timeout=3)
        if res_api.getcode() == 200:
            data = json.loads(res_api.read().decode('utf-8'))
            if data.get('success') is True:
                log_info("    [SUCCESS] 縣市 API 響應正常，資料回傳成功！")
            else:
                log_error("    [FAIL] 縣市 API 回傳 success 非 True！")
                sys.exit(1)
        else:
            log_error(f"    [FAIL] 縣市 API 返回非 200 狀態碼: {res_api.getcode()}")
            sys.exit(1)
            
    except Exception as e:
        log_error(f"動態測試發生異常: {e}")
        if process:
            process.terminate()
        sys.exit(1)
    finally:
        if process:
            log_info("正在關閉臨時測試伺服器...")
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
            log_info("測試伺服器已安全關閉。")

if __name__ == "__main__":
    print("="*60)
    print("🚀 啟動 Git 推播前自動化測試驗證程序 🚀")
    print("="*60)
    
    run_compile_check()
    print("-"*60)
    run_dom_check()
    print("-"*60)
    run_leakage_check()
    print("-"*60)
    run_dynamic_server_check()
    
    print("="*60)
    print("\033[32m[SUCCESS] 所有測試均已順理通過，本機環境安全允許推播！\033[0m")
    print("="*60)
    sys.exit(0)
