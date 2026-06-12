# !/usr/bin/env python
# _*_ coding: utf-8 _*_
"""
手动登录辅助脚本：
打开真实Edge内核浏览器（patchright持久化上下文）-> 用户手动扫码登录Boss直聘
登录态（cookies）会自动保存在 data/edge_profile 目录下，
爬虫复用同一个配置目录即可直接进入已登录状态，无需再单独导出/导入。

使用方法：
    python crawler/login.py
登录成功、能看到职位搜索页面后，回到本终端按回车退出即可。
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from patchright.sync_api import sync_playwright

import config


def main():
    os.makedirs(config.EDGE_PROFILE_DIR, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            config.EDGE_PROFILE_DIR,
            channel="msedge",
            headless=False,
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.zhipin.com/web/user/?ka=header-login", wait_until="domcontentloaded")

        print("请在打开的浏览器窗口中完成登录（扫码或账号密码）。")
        print("登录成功、能看到职位搜索页面后，回到本终端按回车键退出...")
        input()

        print("登录态已随浏览器配置目录保存，爬虫可直接复用，无需再次登录。")
        context.close()


if __name__ == "__main__":
    main()
