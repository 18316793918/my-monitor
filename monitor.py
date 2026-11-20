"""监控软考成绩批次；只有页面出现目标批次才推送 Bark。"""
import os
import re
from urllib.parse import quote

import requests
from playwright.sync_api import sync_playwright

URL = "https://bm.ruankao.org.cn/query/score/main"
TARGET = "2026年下半年"
PREVIOUS = "2026年上半年"


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def check_batch() -> bool:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="zh-CN", timezone_id="Asia/Shanghai")
            response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            if response is None or response.status >= 400:
                raise RuntimeError(f"查询页请求失败：{response.status if response else '无响应'}")
            page.wait_for_timeout(5000)

            # 尝试展开常见的动态下拉框；不填写账号密码，不进行登录。
            for selector in ('[role="combobox"]', '.el-select', '.ant-select-selector', '.layui-form-select'):
                fields = page.locator(selector)
                for index in range(min(fields.count(), 5)):
                    field = fields.nth(index)
                    try:
                        if field.is_visible():
                            field.click(timeout=1200)
                            page.wait_for_timeout(350)
                    except Exception:
                        continue

            # 原生下拉选项 + 常见前端框架下拉选项。
            choices = page.locator(
                'select option, [role="option"], '
                '.el-select-dropdown__item, .ant-select-item-option, '
                '.layui-form-select dd'
            )
            option_text = [compact(s) for s in choices.all_text_contents()]

            # 备选：页面中有一个精确匹配的可见批次文本。
            def visible_exact(label: str) -> bool:
                items = page.get_by_text(label, exact=True)
                return any(items.nth(i).is_visible() for i in range(min(items.count(), 20)))

            if any(TARGET in item for item in option_text) or visible_exact(TARGET):
                print(f"发现目标批次：{TARGET}")
                return True

            if any(PREVIOUS in item for item in option_text) or visible_exact(PREVIOUS):
                print(f"正常：目前仍是{PREVIOUS}，尚未出现{TARGET}")
                return False

            # 无法识别正常批次时，不静默当作“尚未公布”，也不误发成绩提醒。
            page.screenshot(path="debug.png", full_page=True)
            raise RuntimeError("未识别到成绩批次下拉框，可能需要登录、网页结构变更或网站拦截。请查看 Actions 日志与调试截图。")
        finally:
            browser.close()


def notify_bark(title_text: str, message_text: str) -> None:
    bark_url = os.environ["BARK_URL"].rstrip("/")
    title = quote(title_text, safe="")
    message = quote(message_text, safe="")
    response = requests.get(f"{bark_url}/{title}/{message}", params={"url": URL}, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code", "")) != "200":
        raise RuntimeError(f"Bark 推送未成功：{payload}")
    print("Bark 推送成功")


def disable_workflow() -> None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("未在 GitHub Actions 中运行，跳过关闭工作流")
        return
    response = requests.put(
        f"https://api.github.com/repos/{repo}/actions/workflows/watch.yml/disable",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    response.raise_for_status()
    print("已自动停用定时监控工作流")


if __name__ == "__main__":
    if check_batch():
        notify_bark("软考成绩查询入口更新", "检测到“2026年下半年”批次，快去官网查看！")
        disable_workflow()
    elif os.environ.get("SEND_STATUS") == "true":
        notify_bark("软考监控 · 每小时状态", "监控正常，最新已识别批次为2026年上半年，2026年下半年尚未出现。")
