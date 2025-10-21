#!/usr/bin/env python3
"""
增强版 CloudFlare IP 采集器（保留有效站点，提升抓取量）
"""

import os
import re
import time
import random
import logging
from typing import Set, List

import requests
from fake_useragent import UserAgent
import undetected_chromedriver as uc

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

# 核心配置
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
OUTPUT_FILE = "ip.txt"
RETRY_TIMES = 2  # 单站点重试次数（平衡效率与成功率）
TIMEOUT = 12  # 延长超时，适配更多站点
RANDOM_JITTER = (2, 5)  # 随机间隔，降低反爬风险

# 目标站点列表（移除已确认失效的ip.flares.cloud，保留其余所有）
URLS = [
    'https://ip.164746.xyz', 
    'https://cf.090227.xyz', 
    'https://stock.hostmonit.com/CloudFlareYes',
    'https://ip.haogege.xyz/',
    'https://ct.090227.xyz',
    'https://cmcc.090227.xyz',    
    'https://cf.vvhan.com',
    'https://api.uouin.com/cloudflare.html',
    'https://addressesapi.090227.xyz/CloudFlareYes',
    'https://addressesapi.090227.xyz/ip.164746.xyz',
    'https://ipdb.api.030101.xyz/?type=cfv4;proxy',
    'https://ipdb.api.030101.xyz/?type=bestcf&country=true',
    'https://ipdb.api.030101.xyz/?type=bestproxy&country=true',
    'https://www.wetest.vip/page/edgeone/address_v4.html',
    'https://www.wetest.vip/page/cloudfront/address_v4.html',
    'https://www.wetest.vip/page/cloudflare/address_v4.html'
]

# 代理池优化：仅在特定难爬站点使用代理，其余直连
class SmartProxyRotator:
    def __init__(self):
        self.proxies = []
        self._fetch_proxies()
        # 需要代理的难爬站点（根据实际情况调整）
        self.need_proxy_domains = {
            'ipdb.api.030101.xyz',
            'addressesapi.090227.xyz'
        }

    def _fetch_proxies(self):
        """获取高质量代理（改用更稳定的免费代理源）"""
        try:
            # 切换到更稳定的代理API
            proxy_api = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            resp = requests.get(proxy_api, timeout=15)
            self.proxies = [f"http://{p}" for p in resp.text.strip().split() if p]
            random.shuffle(self.proxies)
            logging.info(f"代理池刷新成功，可用代理 {len(self.proxies)} 个")
        except Exception as e:
            logging.warning(f"代理池获取失败，将使用直连: {e}")
            self.proxies = []

    def get(self, url: str) -> str:
        """根据URL判断是否需要使用代理"""
        domain = url.split("//")[-1].split("/")[0]
        if domain not in self.need_proxy_domains:
            return ""  # 直连
        
        if not self.proxies:
            self._fetch_proxies()
        return self.proxies.pop() if self.proxies else ""  # 弹出一个代理使用

# 初始化工具
proxy_rotator = SmartProxyRotator()
ua = UserAgent()

def _random_headers() -> dict:
    """生成更贴近真实浏览器的请求头"""
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": random.choice([
            "https://www.google.com/",
            "https://www.baidu.com/",
            "https://github.com/",
            "https://www.bing.com/"
        ]),
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
    }

def _sleep():
    """随机延迟，模拟人工浏览"""
    time.sleep(random.uniform(*RANDOM_JITTER))

def _sort_ip(ip: str):
    """按IP段排序，便于去重和查看"""
    return tuple(map(int, ip.split(".")))

# ---------- 请求逻辑（增强版） ----------
def requests_fallback(url: str) -> str:
    """智能请求策略：直连优先，难爬站点用代理，最后用浏览器"""
    proxy = proxy_rotator.get(url)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    # 先尝试普通请求
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            logging.info(f"尝试[{attempt}/{RETRY_TIMES}] {url} {f'（代理：{proxy}）' if proxy else ''}")
            resp = requests.get(
                url,
                headers=_random_headers(),
                proxies=proxies,
                timeout=TIMEOUT,
                allow_redirects=True,
                verify=False  # 忽略SSL证书错误（部分站点可能证书过期）
            )
            if 200 <= resp.status_code < 300:
                return resp.text
            logging.warning(f"状态码异常: {resp.status_code}，将重试")
        except Exception as e:
            logging.warning(f"请求失败: {e}")
        _sleep()

    # 普通请求失败，用浏览器重试（增强反爬）
    return _selenium_get(url)

def _selenium_get(url: str) -> str:
    """增强版浏览器请求，提高绕过反爬成功率"""
    logging.info(f"启用增强版 Undetected Chrome 访问: {url}")
    options = uc.ChromeOptions()
    
    # 核心反检测配置
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-data-dir=/tmp/chrome-user-data")  # 模拟用户数据
    options.add_argument("--disable-extensions")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--start-maximized")
    options.add_argument(f"--window-size={random.randint(1200, 1920)},{random.randint(800, 1080)}")
    
    # 随机User-Agent（避免默认值被识别）
    options.add_argument(f"user-agent={ua.random}")
    
    # 禁用无头模式（部分站点检测无头浏览器）
    options.headless = False

    driver = uc.Chrome(options=options)
    try:
        # 移除webdriver标记
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
            """
        })
        
        driver.get(url)
        # 动态等待时间（根据站点难度调整）
        wait_time = random.uniform(6, 10)
        logging.info(f"浏览器等待 {wait_time:.1f} 秒加载页面")
        time.sleep(wait_time)
        
        return driver.page_source
    finally:
        driver.quit()

# ---------- 主流程 ----------
def crawl() -> Set[str]:
    """抓取所有站点的IP，去重后返回"""
    ips = set()
    for url in URLS:
        try:
            html = requests_fallback(url)
            # 提取IP并过滤内网IP（10.x.x.x、192.168.x.x、172.x.x.x）
            raw_ips = IP_PATTERN.findall(html)
            valid_ips = [
                ip for ip in raw_ips
                if not ip.startswith(("10.", "192.168.", "172."))
                and all(0 <= int(seg) <= 255 for seg in ip.split("."))  # 过滤无效IP（如999.999.999.999）
            ]
            ips.update(valid_ips)
            logging.info(f"从 {url} 提取到 {len(valid_ips)} 个有效IP（累计：{len(ips)}）")
        except Exception as e:
            logging.error(f"站点 {url} 处理失败: {e}")
        _sleep()
    return ips

def save(ips: Set[str]):
    """保存IP到文件，确保文件始终存在"""
    sorted_ips = sorted(ips, key=_sort_ip) if ips else []
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips))
    logging.info(f"最终抓取到 {len(sorted_ips)} 个唯一有效IP，已保存到 {OUTPUT_FILE}")

if __name__ == "__main__":
    # 清除旧文件
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    # 执行抓取并保存
    ip_set = crawl()
    save(ip_set)
