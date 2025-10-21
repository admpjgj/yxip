#!/usr/bin/env python3
"""
整合版 Cloudflare IP 采集器（优化后）
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

# -------------------------- 核心配置（优化点：增强IP提取和容错） --------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

# 优化点1：增强IP正则，确保带端口的IP也能被提取
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
IP_WITH_PORT_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d+\b')
OUTPUT_FILE = "ip.txt"
MAX_WORKERS = 4
BASE_TIMEOUT = 12  # 优化点2：延长超时，适配慢加载站点
RANDOM_JITTER = (1, 3)

# -------------------------- 站点列表（保留所有有效站点） --------------------------
URLS = {
    'low': [
        'https://ip.164746.xyz',
        'https://cf.090227.xyz',
        'https://www.wetest.vip/page/cloudflare/address_v4.html',
        'https://cfip.ink',
        'https://cloudflareip.fun',
        'https://ipcf.cc',
        'https://cfip.top'
    ],
    'medium': [
        'https://stock.hostmonit.com/CloudFlareYes',
        'https://api.uouin.com/cloudflare.html',
        'https://ip.haogege.xyz/',
        'https://ip.cfw.ltd',
        'https://cfproxy.net'
    ],
    'high': [
        'https://ipdb.api.030101.xyz/?type=cfv4;proxy',  # 重点优化站点
        'https://addressesapi.090227.xyz/CloudFlareYes',
        'https://cf.ipshelper.com',
        'https://cf.haoip.cc'
    ]
}

# -------------------------- 提取规则（优化点3：增强ipdb站点解析） --------------------------
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

    # 高风险站点规则（优化点：精准匹配ipdb的JS变量）
    'ipdb.api.030101.xyz': {
        'script_pattern': r'var\s+ips\s*=\s*\[([^\]]+)\]',  # 完整匹配变量
        'ip_clean_pattern': r'"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:\d+)"'  # 只提取带端口的有效IP
    },
    'addressesapi.090227.xyz': {'tag': 'pre', 'attrs': {}},
    'cf.ipshelper.com': {'tag': 'div', 'attrs': {'class': 'ip-list'}},
    'cf.haoip.cc': {'tag': 'pre', 'attrs': {}}
}

# -------------------------- 工具类（优化点4：修复fake_useragent和反爬） --------------------------
class AntiBlockTool:
    def __init__(self):
        # 优化点：禁用远程服务器，解决503错误
        self.ua = UserAgent(use_cache_server=False)
        self.headers_pool = self._generate_headers_pool(15)

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
                logging.info(f"直连[{attempt+1}/2] {url}（UA：{headers['User-Agent'][:20]}...）")
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=BASE_TIMEOUT,
                    allow_redirects=True,
                    verify=False
                )
                resp.raise_for_status()
                if IP_PATTERN.search(resp.text) or IP_WITH_PORT_PATTERN.search(resp.text):
                    return resp.text
                logging.warning(f"页面无IP，重试")
            except Exception as e:
                logging.warning(f"直连失败[{attempt+1}]：{e}")
            self.anti_block.dynamic_sleep(risk_level)
        logging.info(f"直连失败，用浏览器访问 {url}")
        return self._fetch_with_browser(url, quick_mode=True)

    def _fetch_high_risk(self, url: str) -> str:
        # 优化点5：针对ipdb站点延长等待时间
        is_ipdb = 'ipdb.api.030101.xyz' in url
        
        if not self.driver:
            self.driver = self._create_driver()
        
        try:
            logging.info(f"浏览器访问高风险站点：{url}")
            self.driver.get(url)
            # 等待验证通过（ipdb站点延长至20秒）
            wait_time = 20 if is_ipdb else 15
            WebDriverWait(self.driver, wait_time).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            # 等待JS渲染IP（ipdb站点延长至8-12秒）
            js_wait = random.uniform(8, 12) if is_ipdb else random.uniform(3, 5)
            logging.info(f"等待JS渲染：{js_wait:.1f}秒")
            time.sleep(js_wait)
            
            page_source = self.driver.page_source
            if IP_PATTERN.search(page_source) or IP_WITH_PORT_PATTERN.search(page_source):
                return page_source
            
            logging.warning(f"无IP，刷新重试")
            self.driver.refresh()
            time.sleep(js_wait)
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
        options.headless = False  # 高风险站点必须关闭无头模式
        driver = uc.Chrome(options=options)
        # 隐藏自动化标记
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        })
        return driver

# -------------------------- IP提取（优化点6：增强ipdb站点提取） --------------------------
def extract_ips(html: str, url: str) -> List[str]:
    if not html:
        logging.warning(f"[{url}] 页面为空")
        return []
    
    # 优化点：优先检查带端口的IP
    has_ip = IP_PATTERN.search(html) or IP_WITH_PORT_PATTERN.search(html)
    if not has_ip:
        logging.warning(f"[{url}] 页面无有效IP")
        return []
    
    # 提取主域名（适配子域名）
    domain = url.split("//")[-1].split("/")[0].split(".")[-2]
    ips = []

    # 优先用站点规则提取
    if domain in SITE_RULES:
        rule = SITE_RULES[domain]
        # 针对ipdb站点的JS变量提取
        if 'script_pattern' in rule:
            # 优化点：使用DOTALL模式匹配多行内容
            script_match = re.search(rule['script_pattern'], html, re.IGNORECASE | re.DOTALL)
            if script_match:
                ips_str = script_match.group(1)
                ips = re.findall(rule['ip_clean_pattern'], ips_str)
                logging.info(f"[{url}] JS规则提取到 {len(ips)} 个IP")
                return ips
        # 其他站点的标签提取
        elif 'tag' in rule:
            soup = BeautifulSoup(html, "lxml")
            target_tag = soup.find(rule['tag'], attrs=rule['attrs'])
            if target_tag:
                content = target_tag.get_text()
                # 优化点：同时提取纯IP和带端口的IP
                ips = IP_PATTERN.findall(content) + IP_WITH_PORT_PATTERN.findall(content)
                logging.info(f"[{url}] 标签规则提取到 {len(ips)} 个IP")
                return ips

    # 通用提取（兜底）
    ips = IP_PATTERN.findall(html) + IP_WITH_PORT_PATTERN.findall(html)
    logging.info(f"[{url}] 通用规则提取到 {len(ips)} 个IP")
    return ips

# -------------------------- 主流程（优化点7：确保文件生成） --------------------------
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

    # 1. 并行处理低风险站点
    logging.info("=== 处理低风险站点（并行） ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_url, url, 'low', fetcher, anti_block) for url in URLS['low']]
        for future in concurrent.futures.as_completed(futures):
            all_ips.update(future.result())

    # 2. 串行处理中高风险站点
    for risk_level in ['medium', 'high']:
        logging.info(f"\n=== 处理{risk_level}风险站点（串行） ===")
        for url in URLS[risk_level]:
            ips = process_url(url, risk_level, fetcher, anti_block)
            all_ips.update(ips)

    # 保存结果（优化点8：强制生成文件，显示保存路径）
    sorted_ips = sorted(all_ips, key=lambda x: tuple(map(int, x.split(":")[0].split("."))))
    try:
        with open(OUTPUT_FILE, "w", encoding="utf8") as f:
            f.write("\n".join(sorted_ips))
        # 显示文件绝对路径
        file_path = os.path.abspath(OUTPUT_FILE)
        logging.info(f"\n=== 抓取完成 ===")
        logging.info(f"总耗时：{time.time() - start_time:.2f}秒")
        logging.info(f"总有效IP数：{len(sorted_ips)}个（已去重）")
        logging.info(f"IP已保存到：{file_path}")
    except Exception as e:
        logging.error(f"保存文件失败！原因：{e}")
        logging.error(f"请检查路径权限：{os.path.abspath(OUTPUT_FILE)}")

if __name__ == "__main__":
    # 优化点9：删除提前删除文件的逻辑，避免误删
    main()
