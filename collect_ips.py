#!/usr/bin/env python3
"""
优化版 CloudFlare IP 采集器（解决抓不到IP问题）
"""

import os
import re
import time
import random
import logging
from typing import Set, List

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import undetected_chromedriver as uc

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
OUTPUT_FILE = "ip.txt"
RETRY_TIMES = 2  # 减少重试次数，避免浪费时间
TIMEOUT = 10  # 延长超时时间
RANDOM_JITTER = (2, 4)  # 增加访问间隔，降低反爬风险

# 精简目标网站（保留经测试有效的）
URLS = [
    'https://ip.164746.xyz',  # 稳定可用
    'https://cf.090227.xyz',  # 稳定可用
    'https://stock.hostmonit.com/CloudFlareYes',  # 稳定可用
    'https://cf.vvhan.com',  # 稳定可用
    'https://www.wetest.vip/page/cloudflare/address_v4.html',  # 稳定可用
]

# 移除不可靠的免费代理池（改用无代理直接访问，避免代理拖慢速度）
class ProxyRotator:
    def get(self) -> str:
        return ""  # 始终返回空（不使用代理）

proxy_rotator = ProxyRotator()
ua = UserAgent()

def _random_headers() -> dict:
    return {
        "User-Agent": ua.random,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.baidu.com/",  # 改用国内Referer，降低风险
        "Connection": "keep-alive",
    }

def _sleep():
    time.sleep(random.uniform(*RANDOM_JITTER))

def _sort_ip(ip: str):
    return tuple(map(int, ip.split(".")))

# ---------- 请求优化 ----------
def requests_fallback(url: str) -> str:
    """优先无代理直接请求，失败后用浏览器"""
    # 先尝试无代理请求（去掉代理，提高成功率）
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            logging.info("尝试[%d/%d] %s", attempt, RETRY_TIMES, url)
            resp = requests.get(
                url,
                headers=_random_headers(),
                timeout=TIMEOUT,
                allow_redirects=True,  # 允许重定向
            )
            resp.raise_for_status()  # 只处理200状态码
            return resp.text
        except Exception as e:
            logging.warning("requests 失败: %s", e)
        _sleep()
    # 浏览器方案增强：延长等待时间，禁用自动化特征
    return _selenium_get(url)

def _selenium_get(url: str) -> str:
    logging.info("启用 Undetected Chrome: %s", url)
    options = uc.ChromeOptions()
    # 增强反检测配置
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-data-dir=/tmp/chrome-user-data")  # 模拟真实用户数据目录
    options.add_argument("--disable-extensions")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.headless = False  # 关闭无头模式（部分网站会检测无头浏览器）
    # 添加随机窗口大小
    options.add_argument(f"--window-size={random.randint(1024, 1280)},{random.randint(768, 900)}")
    
    driver = uc.Chrome(options=options)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })  # 移除webdriver标记
        driver.get(url)
        time.sleep(8)  # 延长等待时间，确保反爬页面加载完成
        return driver.page_source
    finally:
        driver.quit()

# ---------- 主流程 ----------
def crawl() -> Set[str]:
    ips = set()
    for u in URLS:
        try:
            html = requests_fallback(u.strip())
            # 增强IP提取：过滤内网IP（10.x.x.x、192.168.x.x等）
            found = [ip for ip in IP_PATTERN.findall(html) if not ip.startswith(("10.", "192.168.", "172."))]
            ips.update(found)
            logging.info("从 %s 提取到 %d 个有效IP", u, len(found))
        except Exception as e:
            logging.error("最终失败 %s : %s", u, e)
        _sleep()
    return ips

def save(ips: Set[str]):
    # 即使没抓到IP，也生成空文件（避免后续筛选脚本报错）
    sorted_ips = sorted(ips, key=_sort_ip) if ips else []
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips) + "\n")
    logging.info("已保存 %d 条 IP 到 %s", len(sorted_ips), OUTPUT_FILE)

if __name__ == "__main__":
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    ip_set = crawl()
    save(ip_set)
