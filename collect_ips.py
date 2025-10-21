#!/usr/bin/env python3
"""
整合版 Cloudflare IP 采集器（包含所有历史有效站点+新增有效站点）
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
MAX_WORKERS = 4  # 增加线程数，适配更多低风险站点
BASE_TIMEOUT = 10
RANDOM_JITTER = (1, 3)

# -------------------------- 整合所有有效站点（按风险分级） --------------------------
URLS = {
    'low': [  # 直连秒开，100%有效（包含历史有效+新增）
        'https://ip.164746.xyz',  # 历史有效
        'https://cf.090227.xyz',  # 历史有效
        'https://www.wetest.vip/page/cloudflare/address_v4.html',  # 历史有效
        'https://cfip.ink',  # 新增有效
        'https://cloudflareip.fun',  # 新增有效
        'https://ipcf.cc',  # 历史验证有效（低反爬）
        'https://cfip.top'  # 历史验证有效（低反爬）
    ],
    'medium': [  # 直连可访问，稳定有IP
        'https://stock.hostmonit.com/CloudFlareYes',  # 历史有效
        'https://api.uouin.com/cloudflare.html',  # 历史有效
        'https://ip.haogege.xyz/',  # 历史有效
        'https://ip.cfw.ltd',  # 历史验证有效（中反爬）
        'https://cfproxy.net'  # 历史验证有效（中反爬）
    ],
    'high': [  # 需浏览器验证，验证后有IP
        'https://ipdb.api.030101.xyz/?type=cfv4;proxy',  # 历史有效
        'https://addressesapi.090227.xyz/CloudFlareYes',  # 历史有效
        'https://cf.ipshelper.com',  # 历史有效
        'https://cf.haoip.cc'  # 历史验证有效（高反爬）
    ]
}

# -------------------------- 全站点提取规则（覆盖所有有效站点） --------------------------
SITE_RULES: Dict[str, Dict] = {
    # 低风险站点规则
    'ip.164746.xyz': {'tag': 'pre', 'attrs': {}},
    'cf.090227.xyz': {'tag': 'div', 'attrs': {'class': 'ip-list'}},
    'www.wetest.vip': {'tag': 'pre', 'attrs': {'class': 'ip-pre'}},
    'cfip.ink': {'tag': 'pre', 'attrs': {}},
    'cloudflareip.fun': {'tag': 'textarea', 'attrs': {'class': 'ip-text'}},
    'ipcf.cc': {'tag': 'textarea', 'attrs': {}},
    'cfip.top': {'tag': 'pre', 'attrs': {}},

    # 中风险站点规则
    'stock.hostmonit.com': {'tag': 'div', 'attrs': {'class': 'card-body'}},
    'api.uouin.com': {'tag': 'pre', 'attrs': {}},
    'ip.haogege.xyz': {'tag': 'div', 'attrs': {'id': 'ip-content'}},
    'ip.cfw.ltd': {'tag': 'pre', 'attrs': {}},
    'cfproxy.net': {'tag': 'div', 'attrs': {'class': 'proxy-list'}},

    # 高风险站点规则
    'ipdb.api.030101.xyz': {
        'script_pattern': r'var\s+ips\s*=\s*\[([^\]]+)\]',
        'ip_clean_pattern': r'"([^"]+)"'
    },
    'addressesapi.090227.xyz': {'tag': 'pre', 'attrs': {}},
    'cf.ipshelper.com': {'tag': 'div', 'attrs': {'class': 'ip-list'}},
    'cf.haoip.cc': {'tag': 'pre', 'attrs': {}}
}

# -------------------------- 工具类 --------------------------
class AntiBlockTool:
    def __init__(self):
        self.ua = UserAgent()
        self.headers_pool = self._generate_headers_pool(15)  # 更多请求头，适配多站点

    def _generate_headers_pool(self, count: int) -> List[dict]:
        headers_list = []
        referers = ["https://www.google.com/", "https://www.baidu.com/", "https://github.com/", "https://www.bing.com/"]
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
        self.driver = None  # 复用浏览器实例

    def fetch(self, url: str, risk_level: str) -> str:
        if risk_level == 'high':
            return self._fetch_high_risk(url)
        else:
            return self._fetch_low_medium_risk(url, risk_level)

    def _fetch_low_medium_risk(self, url: str, risk_level: str) -> str:
        """低/中风险站点：直连+重试，确保获取有效页面"""
        for attempt in range(2):
            try:
                headers = self.anti_block.get_random_headers()
                logging.info(f"直连[{attempt+1}/2] {url}（UA：{headers['User-Agent'][:20]}...）")
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=BASE_TIMEOUT,
                    allow_redirects=True,
                    verify=False
                )
                resp.raise_for_status()
                # 验证页面是否包含IP（避免空页面）
                if IP_PATTERN.search(resp.text):
                    return resp.text
                logging.warning(f"页面无IP，重试")
            except Exception as e:
                logging.warning(f"直连失败[{attempt+1}]：{e}")
            self.anti_block.dynamic_sleep(risk_level)
        # 直连失败用浏览器兜底
        logging.info(f"直连失败，用浏览器访问 {url}")
        return self._fetch_with_browser(url, quick_mode=True)

    def _fetch_high_risk(self, url: str) -> str:
        """高风险站点：浏览器+验证，确保通过反爬"""
        if not self.driver:
            self.driver = self._create_driver()
        
        try:
            logging.info(f"浏览器访问高风险站点：{url}")
            self.driver.get(url)
            # 等待验证通过（最长15秒）
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            # 等待JS渲染IP
            time.sleep(random.uniform(3, 5))
            page_source = self.driver.page_source
            if IP_PATTERN.search(page_source):
                return page_source
            # 重试一次
            logging.warning(f"无IP，刷新重试")
            self.driver.refresh()
            time.sleep(random.uniform(3, 5))
            return self.driver.page_source
        except Exception as e:
            logging.error(f"高风险站点访问失败：{e}")
            return ""

    def _create_driver(self) -> uc.Chrome:
        options = uc.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.anti_block.ua.random}")
        options.headless = False  # 高风险站点关闭无头模式
        driver = uc.Chrome(options=options)
        # 隐藏自动化标记
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        })
        return driver

# -------------------------- IP提取 --------------------------
def extract_ips(html: str, url: str) -> List[str]:
    if not html or not IP_PATTERN.search(html):
        logging.warning(f"[{url}] 页面无有效IP")
        return []
    
    domain = url.split("//")[-1].split("/")[0].split(".")[-2]  # 提取主域名（适配子域名）
    ips = []

    # 优先用站点规则提取
    if domain in SITE_RULES:
        rule = SITE_RULES[domain]
        soup = BeautifulSoup(html, "lxml")
        if 'script_pattern' in rule:
            script_match = re.search(rule['script_pattern'], html, re.IGNORECASE)
            if script_match:
                ips = re.findall(rule['ip_clean_pattern'], script_match.group(1))
                logging.info(f"[{url}] JS规则提取到 {len(ips)} 个IP")
                return ips
        elif 'tag' in rule:
            target_tag = soup.find(rule['tag'], attrs=rule['attrs'])
            if target_tag:
                content = target_tag.get_text()
                ips = IP_PATTERN.findall(content) + IP_WITH_PORT_PATTERN.findall(content)
                logging.info(f"[{url}] 标签规则提取到 {len(ips)} 个IP")
                return ips

    # 通用提取（兜底）
    ips = IP_PATTERN.findall(html) + IP_WITH_PORT_PATTERN.findall(html)
    logging.info(f"[{url}] 通用规则提取到 {len(ips)} 个IP")
    return ips

# -------------------------- 主流程 --------------------------
def process_url(url: str, risk_level: str, fetcher: SmartFetcher, anti_block: AntiBlockTool) -> Set[str]:
    ips = set()
    try:
        html = fetcher.fetch(url, risk_level)
        raw_ips = extract_ips(html, url)
        # 过滤无效IP
        for ip in raw_ips:
            ip_clean = ip.split(":")[0]
            if (
                len(ip_clean.split(".")) == 4
                and not ip_clean.startswith(("10.", "192.168.", "172."))
                and all(0 <= int(seg) <= 255 for seg in ip_clean.split("."))
            ):
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

    # 1. 并行处理低风险站点（4线程，高效）
    logging.info("=== 处理低风险站点（并行） ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_url, url, 'low', fetcher, anti_block) for url in URLS['low']]
        for future in concurrent.futures.as_completed(futures):
            all_ips.update(future.result())

    # 2. 串行处理中高风险站点（确保反爬绕过）
    for risk_level in ['medium', 'high']:
        logging.info(f"\n=== 处理{risk_level}风险站点（串行） ===")
        for url in URLS[risk_level]:
            ips = process_url(url, risk_level, fetcher, anti_block)
            all_ips.update(ips)

    # 保存结果（去重后）
    sorted_ips = sorted(all_ips, key=lambda x: tuple(map(int, x.split(":")[0].split("."))))
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips))

    # 最终统计
    total_count = len(sorted_ips)
    logging.info(f"\n=== 抓取完成 ===")
    logging.info(f"总耗时：{time.time() - start_time:.2f}秒")
    logging.info(f"总有效IP数：{total_count}个（已去重）")

if __name__ == "__main__":
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
    main()
