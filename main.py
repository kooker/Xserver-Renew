import os
import sys
import json
import time
import random
import logging
import re
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, BrowserContext
from typing import Optional, Tuple

# ================= 0. 常量与目录定义 =================
TELEGRAM_API_BASE_URL = "https://api.telegram.org/bot"
XSERVER_LOGIN_URL = "https://secure.xserver.ne.jp/xapanel/login/xmgame"

# Playwright 元素选择器
SELECTOR_TEXTBOX_ACCOUNT_ID_EMAIL = "XServerアカウントID または メールアドレス"
SELECTOR_ID_PASSWORD = "#user_password"
SELECTOR_BUTTON_LOGIN = "ログインする"
SELECTOR_LINK_GAME_MANAGEMENT = "ゲーム管理"
SELECTOR_LINK_UPGRADE_EXTEND = "アップグレード・期限延長"
SELECTOR_LINK_EXTEND_TERM = "期限を延長する"
SELECTOR_BUTTON_CONFIRM_SCREEN = "確認画面に進む"
SELECTOR_BUTTON_EXTEND_TERM_FINAL = "期限を延長する"
SELECTOR_LINK_BACK = "戻る"

# 统一截图目录
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ================= 1. 工业级日志配置 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= 2. Telegram 通知模块 (带重试机制) =================
def send_telegram_notification(message: str, image_path: Optional[Path] = None, retries: int = 3) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    
    if not token or not chat_id:
        logger.warning("⚠️ 未配置 Telegram Token/ChatID，仅打印日志不推送。")
        return

    for attempt in range(1, retries + 1):
        try:
            if image_path and image_path.exists():
                url = f"{TELEGRAM_API_BASE_URL}{token}/sendPhoto"
                with open(image_path, 'rb') as photo:
                    files = {'photo': photo}
                    data = {'chat_id': chat_id, 'caption': message, 'parse_mode': 'Markdown'}
                    response = requests.post(url, files=files, data=data, timeout=30)
            else:
                url = f"{TELEGRAM_API_BASE_URL}{token}/sendMessage"
                data = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
                response = requests.post(url, json=data, timeout=30)
                
            if response.status_code == 200:
                logger.info("✅ Telegram 推送成功")
                return
            else:
                logger.error(f"❌ Telegram 推送失败 (状态码 {response.status_code}): {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Telegram 推送网络异常 (尝试 {attempt}/{retries}): {e}")
        
        # 指数退避重试
        if attempt < retries:
            time.sleep(2 ** attempt)
            
    logger.error("❌ Telegram 消息推送最终失败。")

# ================= 3. 辅助函数 =================
def parse_remaining_time(page) -> str:
    """从页面文本中正则匹配出剩余时间"""
    try:
        # 等待页面主内容加载完毕代替 hardcode 的 sleep
        page.wait_for_load_state("domcontentloaded")
        body_text = page.locator("body").inner_text()
        
        match_hm = re.search(r"残り(\d+)時間(\d+)分", body_text)
        if match_hm: return f"{match_hm.group(1)}小时{match_hm.group(2)}分"
        
        match_h = re.search(r"残り(\d+)時間", body_text)
        if match_h: return f"{match_h.group(1)}小时"
            
        match_fallback = re.search(r"(\d+)時間(\d+)分", body_text)
        if match_fallback: return f"{match_fallback.group(1)}小时{match_fallback.group(2)}分"
            
        return "未知"
    except Exception as e:
        logger.error(f"解析时间遇到异常: {e}")
        return "解析异常"

def safe_screenshot(page, file_name: str) -> Path:
    """安全截图，防止截图失败阻断主流程"""
    path = SCREENSHOT_DIR / file_name
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception as e:
        logger.error(f"⚠️ 截图失败 {file_name}: {e}")
    return path

# ================= 4. 核心单账号处理逻辑 =================
def process_single_account(context: BrowserContext, username: str, password: str) -> Tuple[bool, str]:
    """返回 (是否成功, 结果描述)"""
    page = context.new_page()
    safe_username = re.sub(r'[^a-zA-Z0-9]', '_', username) # 更安全的用户名净化

    try:
        logger.info(f"[{username}] 正在访问 Xserver xmgame 登录页...")
        page.goto(XSERVER_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")

        # 登录
        page.get_by_role("textbox", name=SELECTOR_TEXTBOX_ACCOUNT_ID_EMAIL).fill(username)
        page.locator(SELECTOR_ID_PASSWORD).fill(password)
        page.get_by_role("button", name=SELECTOR_BUTTON_LOGIN).click()

        # 进入管理页
        page.get_by_role("link", name=SELECTOR_LINK_GAME_MANAGEMENT).click()
        page.wait_for_load_state('networkidle')

        time_before = parse_remaining_time(page)
        logger.info(f"[{username}] 续签前剩余时间: {time_before}")

        # 进入升级页
        page.get_by_role("link", name=SELECTOR_LINK_UPGRADE_EXTEND).click()

        # 检查是否可以续期
        try:
            page.get_by_role("link", name=SELECTOR_LINK_EXTEND_TERM).wait_for(state='visible', timeout=5000)
            page.get_by_role("link", name=SELECTOR_LINK_EXTEND_TERM).click()
        except PlaywrightTimeoutError:
            body_text = page.locator("body").inner_text()
            match = re.search(r"更新をご希望の場合は、(.+?)以降にお試しください。", body_text)
            
            if match:
                msg = f"🟢 *Xserver 续期跳过*\n\n👤 账户: `{username}`\n⚠️ 状态: 尚未续期\n⏱️ 当前剩余: {time_before}\n📅 下次可续期时间: {match.group(1)}"
            else:
                msg = f"🟡 *Xserver 续期跳过*\n\n👤 账户: `{username}`\n⚠️ 未找到延期按钮，可能尚未到期。\n⏱️ 当前剩余: {time_before}"

            logger.info(f"[{username}] 跳过续期: 未到续期时间")
            shot_path = safe_screenshot(page, f"skip_{safe_username}.png")
            send_telegram_notification(msg, shot_path)
            return True, "未到期跳过" # 业务上属于正常情况

        # 执行续期
        page.get_by_role("button", name=SELECTOR_BUTTON_CONFIRM_SCREEN).click()
        logger.info(f"[{username}] 正在点击最终延长按钮...")
        page.get_by_role("button", name=SELECTOR_BUTTON_EXTEND_TERM_FINAL).click()
        page.wait_for_load_state('networkidle')

        # 返回查看最新时间
        page.get_by_role("link", name=SELECTOR_LINK_BACK).click()
        page.wait_for_load_state('networkidle')

        time_after = parse_remaining_time(page)
        logger.info(f"[{username}] 续签后剩余时间: {time_after}")

        success_msg = f"🚀 *Xserver 续期成功*\n\n👤 账户: `{username}`\n✅ 状态: 续期成功\n⏱️ 时间变化: {time_before} ➡️ {time_after}"
        shot_path = safe_screenshot(page, f"success_{safe_username}.png")
        send_telegram_notification(success_msg, shot_path)
        return True, "续期成功"

    except PlaywrightTimeoutError as e:
        error_msg = f"❌ *Xserver 续期异常*\n\n👤 账户: `{username}`\n⚠️ 错误: 页面加载或元素查找超时"
        logger.error(f"[{username}] 超时: {e}")
        shot_path = safe_screenshot(page, f"timeout_{safe_username}.png")
        send_telegram_notification(error_msg, shot_path)
        return False, "页面操作超时"
        
    except Exception as e:
        error_msg = f"❌ *Xserver 续期失败*\n\n👤 账户: `{username}`\n⚠️ 错误: 系统异常 ({str(e)[:50]})"
        logger.error(f"[{username}] 异常: {e}", exc_info=True)
        shot_path = safe_screenshot(page, f"error_{safe_username}.png")
        send_telegram_notification(error_msg, shot_path)
        return False, "脚本内部异常"
        
    finally:
        page.close()

# ================= 5. 主调度框架 =================
def main() -> None:
    accounts_env = os.environ.get("XSERVER_ACCOUNTS")
    if not accounts_env:
        logger.error("❌ 未找到环境变量 XSERVER_ACCOUNTS。请在 Github Secrets 中配置。")
        sys.exit(1)

    try:
        accounts = json.loads(accounts_env)
    except json.JSONDecodeError:
        logger.error("❌ XSERVER_ACCOUNTS 格式错误，必须是合法的 JSON 数组。")
        sys.exit(1)

    if not isinstance(accounts, list) or len(accounts) == 0:
        logger.warning("⚠️ 账户列表为空。")
        sys.exit(0)

    total = len(accounts)
    logger.info(f"🚀 成功加载 {total} 个账户配置，准备执行批处理...")

    success_count = 0
    fail_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage', # 工业级标配：防止 Docker/Actions 共享内存溢出崩溃
                '--window-size=1920,1080'
            ]
        )

        for index, user in enumerate(accounts):
            username = user.get("username", "").strip()
            password = user.get("password", "").strip()
            
            if not username or not password:
                logger.warning(f"⚠️ 第 {index+1} 个账号配置缺失用户名或密码，跳过。")
                fail_count += 1
                continue

            logger.info(f"\n========== 开始处理 [{index + 1}/{total}]: {username} ==========")

            # 工业级隔离：每次新建上下文并设定时区语言，防指纹追踪
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ja-JP',
                timezone_id='Asia/Tokyo'
            )

            is_success, msg = process_single_account(context, username, password)
            if is_success:
                success_count += 1
            else:
                fail_count += 1
                
            context.close()

            # 账号间防风控延迟 (最后一个账号无需等待)
            if index < total - 1:
                delay = random.randint(20, 45)
                logger.info(f"⏳ 防风控机制：等待 {delay} 秒后处理下一个账户...")
                time.sleep(delay)

        browser.close()

    # ================= 6. 最终结果汇总与状态码抛出 =================
    summary = f"🎉 批处理执行完毕！总计: {total} | 成功/跳过: {success_count} | 失败: {fail_count}"
    logger.info(f"\n{summary}")
    
    if fail_count > 0:
        logger.error("⚠️ 存在失败的账号，工作流将标记为失败状态。")
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
