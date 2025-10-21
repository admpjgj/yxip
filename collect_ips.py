#!/usr/bin/env python3
"""
增强版 IP 采集器（专门修复 ipdb.api.030101.xyz 站点抓取问题）
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
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

# 核心配置
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
# 针对 ipdb.api.030101.xyz 的特殊IP格式（可能包含端口，如 1.2.3.4:80）
IP_WITH_PORT_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d+\b')
OUTPUT_FILE = "ip.txt"
RETRY_TIMES = 3  # 增加该站点的重试次数
TIMEOUT = 15
RANDOM_JITTER = (3, 6)

# 目标站点列表
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
    'https://ipdb.api.030101.xyz/?type=cfv4;proxy',  # 重点修复
    'https://ipdb.api.030101.xyz/?type=bestcf&country=true',  # 同域名站点
    'https://ipdb.api.030101.xyz/?type=bestproxy&country=true',  # 同域名站点
    'https://www.wetest.vip/page/edgeone/address_v4.html',
    'https://www.wetest.vip/page/cloudfront/address_v4.html',
    'https://www.wetest.vip/page/cloudflare/address_v4.html'
]

# 站点特殊处理规则（重点新增 ipdb.api.030101.xyz 规则）
SITE_RULES = {
    'api.uouin.com': {'tag': 'pre', 'attrs': {}},
    'cf.vvhan.com': {'tag': 'textarea', 'attrs': {'id': 'iparea'}},
    'stock.hostmonit.com': {'tag': 'div', 'attrs': {'class': 'card-body'}},
    # ipdb.api.030101.xyz 的IP藏在JavaScript变量中
    'ipdb.api.030101.xyz': {
        'script_pattern': r'var\s+ips\s*=\s*\[([^\]]+)\]',  # 匹配 var ips = [ ... ]
        'ip_clean_pattern': r'"([^"]+)"'  # 从匹配结果中提取IP字符串
    }
}

class SmartProxyRotator:
    def __init__(self):
        self.proxies = []
        self._fetch_proxies()
        self.need_proxy_domains = {'ipdb.api.030101.xyz', 'addressesapi.090227.xyz'}

    def _fetch_proxies(self):
        try:
            proxy_api = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            resp = requests.get(proxy_api, timeout=15)
            self.proxies = [f"http://{p}" for p in resp.text.strip().split() if p]
            random.shuffle(self.proxies)
            logging.info(f"代理池刷新成功，可用代理 {len(self.proxies)} 个")
        except Exception as e:
            logging.warning(f"代理池获取失败，将使用直连: {e}")
            self.proxies = []

    def get(self, url: str) -> str:
        domain = url.split("//")[-1].split("/")[0]
        if domain not in self.need_proxy_domains:
            return ""
        if not self.proxies:
            self._fetch_proxies()
        return self.proxies.pop() if self.proxies else ""

proxy_rotator = SmartProxyRotator()
ua = UserAgent()

def _random_headers() -> dict:
    return {
        "User-Agent": ua.random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.7,en;q=0.3",
        "Referer": random.choice(["https://www.google.com/", "https://www.baidu.com/"]),
        "Connection": "keep-alive",
    }

def _sleep():
    time.sleep(random.uniform(*RANDOM_JITTER))

def _sort_ip(ip: str):
    # 移除端口后排序（如 1.2.3.4:80 → 1.2.3.4）
    ip_clean = ip.split(":")[0]
    return tuple(map(int, ip_clean.split(".")))

# ---------- 关键修复：增强IP提取逻辑（针对 ipdb.api.030101.xyz） ----------
def extract_ips_from_html(html: str, url: str) -> List[str]:
    """根据不同网站的结构，精准提取IP（重点处理 ipdb 站点）"""
    domain = url.split("//")[-1].split("/")[0]
    ips = []

    # 1. 处理 ipdb.api.030101.xyz 站点（IP藏在JavaScript变量中）
    if domain == 'ipdb.api.030101.xyz':
        rule = SITE_RULES[domain]
        # 从HTML中匹配包含IP的JavaScript变量（如 var ips = ["1.2.3.4:80", ...]）
        script_match = re.search(rule['script_pattern'], html, re.IGNORECASE)
        if script_match:
            # 提取变量中的内容（如 ["1.2.3.4:80", "5.6.7.8:443"]）
            ips_str = script_match.group(1)
            # 从内容中提取所有IP（带端口）
            ip_matches = re.findall(rule['ip_clean_pattern'], ips_str)
            ips = ip_matches
            logging.info(f"从 {domain} 的JavaScript中提取到 {len(ips)} 个IP（带端口）")
        return ips

    # 2. 处理其他站点的特殊规则
    if domain in SITE_RULES and 'tag' in SITE_RULES[domain]:
        rule = SITE_RULES[domain]
        soup = BeautifulSoup(html, "html.parser")
        target_tag = soup.find(rule['tag'], attrs=rule['attrs'])
        if target_tag:
            content = target_tag.get_text()
            ips = IP_PATTERN.findall(content)
            logging.info(f"使用特殊规则从 {domain} 提取到 {len(ips)} 个IP")
            return ips
    
    # 3. 通用提取（全页面搜索）
    all_text = BeautifulSoup(html, "html.parser").get_text()
    ips = IP_PATTERN.findall(all_text)
    # 补充提取带端口的IP（如 1.2.3.4:80）
    ips_with_port = IP_WITH_PORT_PATTERN.findall(all_text)
    ips.extend(ips_with_port)
    return ips

# ---------- 请求逻辑（增强 ipdb 站点的浏览器处理） ----------
def requests_fallback(url: str) -> str:
    domain = url.split("//")[-1].split("/")[0]
    proxy = proxy_rotator.get(url)
    proxies = {"http": proxy, "https": proxy} if proxy else None

    # 对 ipdb 站点优先使用浏览器请求（因为反爬严格）
    if domain == 'ipdb.api.030101.xyz':
        logging.info(f"{domain} 反爬严格，直接使用浏览器请求")
        return _selenium_get(url)

    # 其他站点先尝试普通请求
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            logging.info(f"尝试[{attempt}/{RETRY_TIMES}] {url} {f'（代理：{proxy}）' if proxy else ''}")
            resp = requests.get(
                url,
                headers=_random_headers(),
                proxies=proxies,
                timeout=TIMEOUT,
                allow_redirects=True,
                verify=False
            )
            if 200 <= resp.status_code < 300:
                return resp.text
            logging.warning(f"状态码异常: {resp.status_code}")
        except Exception as e:
            logging.warning(f"请求失败: {e}")
        _sleep()

    return _selenium_get(url)

def _selenium_get(url: str) -> str:
    """增强浏览器请求，确保通过 Cloudflare 验证"""
    logging.info(f"启用增强版 Undetected Chrome 访问: {url}")
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-data-dir=/tmp/chrome-user-data")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"user-agent={ua.random}")
    options.headless = False  # 必须关闭无头模式，否则无法通过5秒盾

    driver = uc.Chrome(options=options)
    try:
        # 移除自动化标记
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {}, };
                window.navigator.languages = ['zh-CN', 'zh'];
            """
        })
        driver.get(url)
        # 针对 Cloudflare 5秒盾，延长等待时间（至少10秒）
        wait_time = random.uniform(10, 15)
        logging.info(f"等待 {wait_time:.1f} 秒以通过反爬验证")
        time.sleep(wait_time)
        return driver.page_source
    finally:
        driver.quit()

# ---------- 主流程 ----------
def crawl() -> Set[str]:
    ips = set()
    for url in URLS:
        try:
            html = requests_fallback(url)
            raw_ips = extract_ips_from_html(html, url)
            # 过滤无效IP（保留带端口的IP，但验证IP部分有效性）
            valid_ips = []
            for ip in raw_ips:
                ip_clean = ip.split(":")[0]  # 移除端口
                # 验证IP格式（0-255的四段数字）
                if (not ip_clean.startswith(("10.", "192.168.", "172.")) 
                    and all(0 <= int(seg) <= 255 for seg in ip_clean.split("."))):
                    valid_ips.append(ip)  # 保留原始格式（可能带端口）
            ips.update(valid_ips)
            logging.info(f"从 {url} 提取到 {len(valid_ips)} 个有效IP（累计：{len(ips)}）")
        except Exception as e:
            logging.error(f"站点 {url} 处理失败: {e}")
        _sleep()
    return ips

def save(ips: Set[str]):
    sorted_ips = sorted(ips, key=_sort_ip) if ips else []
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips))
    logging.info(f"最终抓取到 {len(sorted_ips)} 个唯一有效IP，已保存到 {OUTPUT_FILE}")

if __name__ == "__main__":
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    ip_set = crawl()
    save(ip_set)
