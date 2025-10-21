#!/usr/bin/env python3
"""
高效版 IP 采集器（优化速度+平衡反爬）
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

# -------------------------- 核心配置（速度优化） --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

# IP提取正则
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
IP_WITH_PORT_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d+\b')
OUTPUT_FILE = "ip.txt"
MAX_WORKERS = 3  # 并行处理低风险站点的线程数
GLOBAL_RETRY = 1  # 减少重试次数（速度优先）
BASE_TIMEOUT = 8  # 缩短超时时间
RANDOM_JITTER = (1, 3)  # 缩短基础延迟

# 目标站点分级（按反爬强度）
URLS = {
    # 低反爬：并行处理，快速抓取
    'low': [
        'https://ip.164746.xyz',
        'https://cf.090227.xyz',
        'https://cf.vvhan.com',
        'https://www.wetest.vip/page/cloudflare/address_v4.html',
    ],
    # 中反爬：串行处理，中等延迟
    'medium': [
        'https://stock.hostmonit.com/CloudFlareYes',
        'https://ip.haogege.xyz/',
        'https://ct.090227.xyz',
        'https://cmcc.090227.xyz',
    ],
    # 高反爬：串行处理，必要验证（不并行，避免触发反爬）
    'high': [
        'https://api.uouin.com/cloudflare.html',
        'https://addressesapi.090227.xyz/CloudFlareYes',
        'https://ipdb.api.030101.xyz/?type=cfv4;proxy',
        'https://ipdb.api.030101.xyz/?type=bestcf&country=true',
    ]
}

# 站点提取规则
SITE_RULES: Dict[str, Dict] = {
    'api.uouin.com': {'tag': 'pre', 'attrs': {}},
    'cf.vvhan.com': {'tag': 'textarea', 'attrs': {'id': 'iparea'}},
    'stock.hostmonit.com': {'tag': 'div', 'attrs': {'class': 'card-body'}},
    'ipdb.api.030101.xyz': {
        'script_pattern': r'var\s+ips\s*=\s*\[([^\]]+)\]',
        'ip_clean_pattern': r'"([^"]+)"'
    }
}

# -------------------------- 反爬工具（精简版） --------------------------
class AntiBlockTool:
    def __init__(self):
        self.ua = UserAgent()
        self.headers_pool = self._generate_headers_pool(10)  # 减少请求头池大小

    def _generate_headers_pool(self, count: int) -> List[dict]:
        headers_list = []
        referers = ["https://www.google.com/", "https://www.baidu.com/", "https://github.com/"]
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
        # 缩短各等级延迟
        base = {'low': (0.5, 1.5), 'medium': (1.5, 3), 'high': (3, 5)}[risk_level]
        sleep_time = random.uniform(*base)
        logging.info(f"延迟 {sleep_time:.1f} 秒（{risk_level}）")
        time.sleep(sleep_time)

# -------------------------- 核心请求逻辑（速度优先） --------------------------
class SmartFetcher:
    def __init__(self, anti_block: AntiBlockTool):
        self.anti_block = anti_block
        self.driver = None  # 浏览器实例复用

    def fetch(self, url: str, risk_level: str) -> str:
        if risk_level == 'high':
            return self._fetch_with_browser(url)
        else:
            try:
                return self._fetch_with_requests(url)
            except:
                return self._fetch_with_browser(url, quick_mode=True)

    def _fetch_with_requests(self, url: str) -> str:
        """快速直连：减少超时和重试"""
        headers = self.anti_block.get_random_headers()
        logging.info(f"直连 {url}（UA：{headers['User-Agent'][:20]}...）")
        resp = requests.get(
            url,
            headers=headers,
            timeout=BASE_TIMEOUT,
            allow_redirects=True,
            verify=False
        )
        resp.raise_for_status()
        return resp.text

    def _fetch_with_browser(self, url: str, quick_mode: bool = False) -> str:
        """浏览器请求：精简等待步骤"""
        if not self.driver:
            self.driver = self._create_driver(quick_mode)
        
        try:
            logging.info(f"浏览器访问 {url}（{ '快速模式' if quick_mode else '标准模式' }）")
            self.driver.get(url)
            
            # 快速模式：缩短等待时间
            wait_time = 3 if quick_mode else 8
            WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # 高反爬站点必要等待（但缩短至5秒内）
            if not quick_mode:
                time.sleep(random.uniform(2, 5))
            
            return self.driver.page_source
        except:
            # 失败不重试，直接返回（速度优先）
            logging.warning(f"浏览器访问 {url} 超时，跳过")
            return ""

    def _create_driver(self, quick_mode: bool) -> uc.Chrome:
        """简化浏览器配置，加快启动速度"""
        options = uc.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.anti_block.ua.random}")
        
        # 快速模式强制无头（启动更快）
        if quick_mode:
            options.headless = True
        else:
            options.headless = False
        
        driver = uc.Chrome(options=options)
        # 简化反检测脚本（减少初始化时间）
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        })
        return driver

# -------------------------- IP提取（高效版） --------------------------
def extract_ips(html: str, url: str) -> List[str]:
    if not html:
        return []
    domain = url.split("//")[-1].split("/")[0]
    ips = []

    # 优先用特殊规则
    if domain in SITE_RULES:
        rule = SITE_RULES[domain]
        if 'script_pattern' in rule:
            script_match = re.search(rule['script_pattern'], html, re.IGNORECASE)
            if script_match:
                ips = re.findall(rule['ip_clean_pattern'], script_match.group(1))
                return ips
        elif 'tag' in rule:
            soup = BeautifulSoup(html, "lxml")  # 用lxml解析器（更快）
            target_tag = soup.find(rule['tag'], attrs=rule['attrs'])
            if target_tag:
                content = target_tag.get_text()
                return IP_PATTERN.findall(content) + IP_WITH_PORT_PATTERN.findall(content)

    # 通用提取（简化解析）
    ips = IP_PATTERN.findall(html) + IP_WITH_PORT_PATTERN.findall(html)
    return ips

# -------------------------- 主流程（并行优化） --------------------------
def process_url(url: str, risk_level: str, fetcher: SmartFetcher, anti_block: AntiBlockTool) -> Set[str]:
    """单URL处理函数（用于并行）"""
    ips = set()
    try:
        html = fetcher.fetch(url, risk_level)
        raw_ips = extract_ips(html, url)
        # 快速过滤IP
        for ip in raw_ips:
            ip_clean = ip.split(":")[0]
            if len(ip_clean.split(".")) == 4 and not ip_clean.startswith(("10.", "192.168.")):
                ips.add(ip)
        logging.info(f"[{url}] 提取 {len(ips)} 个IP")
    except Exception as e:
        logging.error(f"[{url}] 失败：{e}")
    anti_block.dynamic_sleep(risk_level)
    return ips

def main():
    anti_block = AntiBlockTool()
    fetcher = SmartFetcher(anti_block)
    all_ips: Set[str] = set()

    # 1. 并行处理低风险站点（速度核心优化）
    logging.info("开始并行处理低风险站点...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for url in URLS['low']:
            futures.append(executor.submit(
                process_url, url, 'low', fetcher, anti_block
            ))
        # 收集结果
        for future in concurrent.futures.as_completed(futures):
            all_ips.update(future.result())

    # 2. 串行处理中高风险站点（避免反爬）
    for risk_level in ['medium', 'high']:
        logging.info(f"开始处理{risk_level}风险站点...")
        for url in URLS[risk_level]:
            ips = process_url(url, risk_level, fetcher, anti_block)
            all_ips.update(ips)

    # 保存结果
    sorted_ips = sorted(all_ips, key=lambda x: tuple(map(int, x.split(":")[0].split("."))))
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips))
    logging.info(f"最终抓取 {len(sorted_ips)} 个IP，耗时：{time.time() - start_time:.2f}秒")

if __name__ == "__main__":
    start_time = time.time()
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    main()
