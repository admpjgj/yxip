#!/usr/bin/env python3
"""
Cloudflare IP 采集器（适配http://ip.flares.cloud/动态渲染）
"""

import os
import re
import time
import random
import logging
import concurrent.futures
from typing import Set, List, Dict

import requests
from fake_useragent import UserAgent
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# -------------------------- 核心配置 --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
IP_WITH_PORT_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d+\b')
OUTPUT_FILE = "ip.txt"
MAX_WORKERS = 4
BASE_TIMEOUT = 12
RANDOM_JITTER = (1, 3)

# -------------------------- 站点列表（将ip.flares.cloud移至high风险，强制浏览器访问） --------------------------
URLS = {
    'low': [
        'https://ip.164746.xyz',
        'https://cf.090227.xyz',
        'https://www.wetest.vip/page/cloudflare/address_v4.html',
    ],
    'medium': [
        'https://stock.hostmonit.com/CloudFlareYes',
        'https://api.uouin.com/cloudflare.html',
        'https://ip.haogege.xyz/',
    ],
    'high': [
        'http://ip.flares.cloud/',  # 移至high风险，用浏览器加载JS
        'https://ipdb.api.030101.xyz/?type=cfv4;proxy',
        'https://addressesapi.090227.xyz/CloudFlareYes',
    ]
}

# -------------------------- 提取规则 --------------------------
SITE_RULES: Dict[str, Dict] = {
    'ip.flares.cloud': {  # 适配该站点的动态标签
        'tag': 'div', 
        'attrs': {'class': 'tabulator-cell', 'tabulator-field': 'ip'}
    },
    # 其他站点规则不变...
    'ip.164746.xyz': {'tag': 'pre', 'attrs': {}},
    'cf.090227.xyz': {'tag': 'div', 'attrs': {'class': 'ip-list'}},
    'www.wetest.vip': {'tag': 'pre', 'attrs': {'class': 'ip-pre'}},
    'stock.hostmonit.com': {'tag': 'div', 'attrs': {'class': 'card-body'}},
    'api.uouin.com': {'tag': 'pre', 'attrs': {}},
    'ip.haogege.xyz': {'tag': 'div', 'attrs': {'id': 'ip-content'}},
    'ipdb.api.030101.xyz': {
        'script_pattern': r'var\s+ips\s*=\s*\[([^\]]+)\]',
        'ip_clean_pattern': r'"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:\d+)"'
    },
    'addressesapi.090227.xyz': {'tag': 'pre', 'attrs': {}},
}

# -------------------------- 工具类 --------------------------
class AntiBlockTool:
    def __init__(self):
        self.ua = UserAgent()
        self.headers_pool = self._generate_headers_pool(15)

    def _generate_headers_pool(self, count: int) -> List[dict]:
        headers_list = []
        referers = ["https://www.google.com/", "https://www.baidu.com/"]
        for _ in range(count):
            headers = {
                "User-Agent": self.ua.random,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": random.choice(referers),
                "Connection": "keep-alive",
            }
            headers_list.append(headers)
        return headers_list

    def get_random_headers(self) -> dict:
        return random.choice(self.headers_pool)

    def dynamic_sleep(self, risk_level: str):
        base = {'low': (0.5, 1.5), 'medium': (1.5, 3), 'high': (3, 5)}[risk_level]
        sleep_time = random.uniform(*base)
        logging.info(f"延迟 {sleep_time:.1f} 秒（{risk_level}）")
        time.sleep(sleep_time)

class SmartFetcher:
    def __init__(self, anti_block: AntiBlockTool):
        self.anti_block = anti_block
        self.driver = None

    def fetch(self, url: str, risk_level: str) -> str:
        if risk_level == 'high':
            return self._fetch_high_risk(url)
        else:
            return self._fetch_low_medium_risk(url, risk_level)

    def _fetch_low_medium_risk(self, url: str, risk_level: str) -> str:
        for attempt in range(2):
            try:
                headers = self.anti_block.get_random_headers()
                logging.info(f"直连[{attempt+1}/2] {url}")
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=BASE_TIMEOUT,
                    allow_redirects=True,
                    verify=False
                )
                resp.raise_for_status()
                if IP_PATTERN.search(resp.text):
                    return resp.text
                logging.warning(f"页面无IP，重试")
            except Exception as e:
                logging.warning(f"直连失败：{e}")
            self.anti_block.dynamic_sleep(risk_level)
        return self._fetch_with_browser(url, quick_mode=True)

    def _fetch_high_risk(self, url: str) -> str:
        # 针对ip.flares.cloud的特殊处理：延长JS渲染等待
        is_flares = 'ip.flares.cloud' in url
        
        if not self.driver:
            self.driver = self._create_driver()
        
        try:
            logging.info(f"浏览器访问 {url}")
            self.driver.get(url)
            # 等待IP表格加载完成（最长20秒）
            wait_time = 20 if is_flares else 15
            WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.tabulator-cell[tabulator-field='ip']"))
            )
            # 额外等待JS渲染IP（该站点需要更长时间）
            js_wait = random.uniform(8, 12) if is_flares else random.uniform(5, 8)
            logging.info(f"等待JS渲染IP：{js_wait:.1f}秒")
            time.sleep(js_wait)
            
            return self.driver.page_source
        except Exception as e:
            logging.error(f"浏览器访问失败：{e}")
            return ""

    def _create_driver(self) -> uc.Chrome:
        options = uc.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.anti_block.ua.random}")
        options.headless = False  # 必须关闭无头模式
        driver = uc.Chrome(options=options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        })
        return driver

# -------------------------- IP提取（增强ip.flares.cloud提取） --------------------------
def extract_ips(html: str, url: str) -> List[str]:
    if not html:
        return []
    
    domain = url.split("//")[-1].split("/")[0].split(".")[-2]
    ips = []

    # 重点处理ip.flares.cloud
    if domain == 'ip.flares.cloud':
        soup = BeautifulSoup(html, "lxml")
        # 查找所有IP标签（该网站用表格展示，多个IP标签）
        ip_tags = soup.find_all('div', {'class': 'tabulator-cell', 'tabulator-field': 'ip'})
        for tag in ip_tags:
            ip = tag.get_text().strip()
            if IP_PATTERN.match(ip):  # 验证是否为有效IP
                ips.append(ip)
        logging.info(f"[{url}] 提取到 {len(ips)} 个IP")
        return ips

    # 其他站点提取逻辑
    if domain in SITE_RULES:
        rule = SITE_RULES[domain]
        if 'script_pattern' in rule:
            script_match = re.search(rule['script_pattern'], html, re.IGNORECASE | re.DOTALL)
            if script_match:
                ips = re.findall(rule['ip_clean_pattern'], script_match.group(1))
                return ips
        elif 'tag' in rule:
            soup = BeautifulSoup(html, "lxml")
            target_tags = soup.find_all(rule['tag'], attrs=rule['attrs'])
            if target_tags:
                for tag in target_tags:
                    content = tag.get_text().strip()
                    if IP_PATTERN.match(content):
                        ips.append(content)
                return ips

    return IP_PATTERN.findall(html)

# -------------------------- 主流程 --------------------------
def process_url(url: str, risk_level: str, fetcher: SmartFetcher, anti_block: AntiBlockTool) -> Set[str]:
    ips = set()
    try:
        html = fetcher.fetch(url, risk_level)
        raw_ips = extract_ips(html, url)
        for ip in raw_ips:
            ip_clean = ip.split(":")[0]
            if len(ip_clean.split(".")) == 4 and not ip_clean.startswith(("10.", "192.168.")):
                ips.add(ip)
        logging.info(f"[{url}] 有效IP：{len(ips)} 个")
    except Exception as e:
        logging.error(f"[{url}] 处理失败：{e}")
    anti_block.dynamic_sleep(risk_level)
    return ips

def main():
    start_time = time.time()
    anti_block = AntiBlockTool()
    fetcher = SmartFetcher(anti_block)
    all_ips: Set[str] = set()

    logging.info("=== 处理低风险站点（并行） ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_url, url, 'low', fetcher, anti_block) for url in URLS['low']]
        for future in concurrent.futures.as_completed(futures):
            all_ips.update(future.result())

    for risk_level in ['medium', 'high']:
        logging.info(f"\n=== 处理{risk_level}风险站点 ===")
        for url in URLS[risk_level]:
            ips = process_url(url, risk_level, fetcher, anti_block)
            all_ips.update(ips)

    sorted_ips = sorted(all_ips, key=lambda x: tuple(map(int, x.split(":")[0].split("."))))
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips))
    logging.info(f"总IP数：{len(sorted_ips)}，保存至 {os.path.abspath(OUTPUT_FILE)}")

if __name__ == "__main__":
    main()
