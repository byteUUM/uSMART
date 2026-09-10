"""
手动登录并保存登录态
=====================
由于客户后台使用 CAS 统一认证（登录态在服务端 cookie 里），无法简单注入 token，
因此采用「手动登录一次、保存状态、后续自动复用」的方案。

用法：
    python save_login.py

脚本会弹出一个带界面的浏览器，自动打开客户首页并跳转到统一认证登录页。
请在浏览器里完成登录，直到看到「客户主页」后台界面为止。
脚本会自动轮询检测登录状态：一旦检测到已回到 admin-sit 后台页面（离开 CAS 登录页），
就自动把登录态保存到 auth_state.json 并退出，无需手动按回车。

之后运行 test_option_trade_records.py 时会自动加载这个文件，无需再次登录，
直到该登录态过期（CAS 会话失效）为止。届时重新跑一次本脚本即可。
"""
import time

from playwright.sync_api import sync_playwright

import config

# CAS 统一认证登录页的特征（出现这些说明还没登录）
LOGIN_PAGE_MARKERS = ("/login", "service=", "统一认证")
# 最长等待登录时间（秒）
MAX_WAIT_SECONDS = 300


def is_logged_in(page) -> bool:
    """判断是否已登录成功：URL 回到 admin-sit 且不在 CAS 登录页。"""
    url = page.url or ""
    if "admin-sit.yxzq.com" not in url:
        return False
    if any(m in url for m in ("/login", "service=")):
        return False
    return True


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("正在打开客户首页，将会跳转到统一认证登录页...")
        page.goto(config.CLIENT_FIRST_PAGE, wait_until="domcontentloaded", timeout=60000)

        print("\n" + "=" * 60)
        print("请在弹出的浏览器窗口中完成登录。")
        print("登录成功、看到后台「客户主页」界面后，脚本会自动保存，无需按回车。")
        print("=" * 60)

        # 先等页面完成到登录页的跳转，避免把初始 goto 的瞬时状态误判为已登录
        time.sleep(5)

        deadline = time.time() + MAX_WAIT_SECONDS
        saved = False
        while time.time() < deadline:
            cookies = context.cookies()
            # 判定成功：已回到 admin-sit 后台页面，且确实拿到了登录 cookie
            if is_logged_in(page) and len(cookies) > 0:
                # 再稳一下，确保后台首页资源和 cookie 都落地
                time.sleep(3)
                cookies = context.cookies()
                if is_logged_in(page) and len(cookies) > 0:
                    context.storage_state(path=str(config.AUTH_STATE_FILE))
                    print(f"\n检测到已登录（{len(cookies)} 个 cookie），登录态已保存到: {config.AUTH_STATE_FILE}")
                    print("现在可以运行: python test_option_trade_records.py")
                    saved = True
                    break
            time.sleep(2)

        if not saved:
            print("\n等待登录超时（5分钟）或未检测到有效登录 cookie，未保存登录态。")
            print("请确认是在这个自动弹出的浏览器窗口里完成登录，然后重跑 save_login.py。")

        browser.close()


if __name__ == "__main__":
    main()
