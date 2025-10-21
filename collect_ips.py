#!/usr/bin/env python3
"""
CloudFlare IP 采集器
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

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

# 核心配置
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')  # 匹配纯IP
IP_WITH_PORT_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d+\b')  # 匹配带端口的IP
OUTPUT_FILE = "ip.txt"  # 输出文件
RETRY_TIMES = 2  # 重试次数
TIMEOUT = 10  # 超时时间
RANDOM_JITTER = (1, 3)  # 随机延迟区间

# 目标站点（实测有效，按反爬强度排序）
URLS = [
    # 低反爬（必出IP）
    'https://www.cloudflare.com/ips-v4',  # Cloudflare官方IP列表
    'https://cf-ip.cdtools.click',  # 明文IP，无反爬
    'https://ip.164746.xyz',  # 稳定产出
    # 中反爬（需简单解析）
    'https://api.uouin.com/cloudflare.html',  # IP在<pre>标签
    'https://cf.090227.xyz',  # 表格形式IP
    'https://www.wetest.vip/page/cloudflare/address_v4.html',
    # 高反爬（需浏览器验证）
    'https://ipdb.api.030101.xyz/?type=cfv4;proxy',  # JS藏IP
    'https://addressesapi.090227.xyz/CloudFlareYes',
]

# 站点IP提取规则（精准定位IP位置）
SITE_RULES = {
    'api.uouin.com': {'tag': 'pre', 'attrs': {}},  # IP在<pre>标签内
    'ipdb.api.030101.xyz': {  # IP在JS变量var ips = []中
        'script_pattern': r'var\s+ips\s*=\s*\[([^\]]+)\]',
        'ip_clean_pattern': r'"([^"]+)"'
    },
    'cf-ip.cdtools.click': {'tag': 'textarea', 'attrs': {}},  # IP在文本框内
    'www.cloudflare.com': {'tag': 'pre', 'attrs': {}},  # 官方IP在<pre>内
    'cf.090227.xyz': {'tag': 'div', 'attrs': {'class': 'ip-list'}},  # IP在列表div内
}

# ---------- 工具类 ----------
class ProxyRotator:
    """简化代理池，高反爬站点用直连更稳定"""
    def get(self) -> str:
        return ""  # 禁用代理，直接访问

class IPCollector:
    def __init__(self):
        self.proxy_rotator = ProxyRotator()
        # 修复fake_useragent远程服务器失效问题
        self.ua = UserAgent(use_cache_server=False)

    def _random_headers(self) -> dict:
        """生成随机请求头"""
        return {
            "User-Agent": self.ua.random,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": random.choice(["https://www.baidu.com/", "https://www.google.com/"]),
            "DNT": "1",
            "Connection": "keep-alive",
        }

    def _sleep(self):
        """随机延迟，模拟人工操作"""
        time.sleep(random.uniform(*RANDOM_JITTER))

    def _fetch_with_requests(self, url: str) -> str:
        """用requests获取页面（低/中反爬站点）"""
        for attempt in range(1, RETRY_TIMES + 1):
            try:
                headers = self._random_headers()
                logging.info(f"请求[{attempt}/{RETRY_TIMES}] {url}")
                resp = requests.get(
                    url,
                    headers=headers,
                    timeout=TIMEOUT,
                    verify=False  # 忽略SSL证书错误
                )
                resp.raise_for_status()  # 只接受200状态码
                return resp.text
            except Exception as e:
                logging.warning(f"requests失败: {e}")
            self._sleep()
        return ""  # 失败返回空

    def _fetch_with_browser(self, url: str) -> str:
        """用浏览器获取页面（高反爬站点）"""
        logging.info(f"浏览器访问 {url}")
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.ua.random}")
        options.headless = False  # 关闭无头模式，避免被识别

        driver = uc.Chrome(options=options)
        try:
            # 隐藏自动化痕迹
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            })
            driver.get(url)
            time.sleep(8)  # 延长等待，确保通过反爬验证
            return driver.page_source
        except Exception as e:
            logging.warning(f"浏览器访问失败: {e}")
            return ""
        finally:
            driver.quit()

    def fetch_page(self, url: str) -> str:
        """根据站点自动选择请求方式"""
        domain = url.split("//")[-1].split("/")[0]
        # 高反爬站点用浏览器，其余用requests
        if domain in ['ipdb.api.030101.xyz', 'addressesapi.090227.xyz']:
            return self._fetch_with_browser(url)
        else:
            return self._fetch_with_requests(url)

    def extract_ips(self, html: str, url: str) -> List[str]:
        """从页面中提取并过滤有效IP"""
        if not html:
            return []
        
        domain = url.split("//")[-1].split("/")[0]
        ips = []

        # 1. 用站点规则精准提取
        if domain in SITE_RULES:
            rule = SITE_RULES[domain]
            if 'script_pattern' in rule:
                # 提取JS变量中的IP（如ipdb站点）
                script_match = re.search(rule['script_pattern'], html, re.IGNORECASE)
                if script_match:
                    ips = re.findall(rule['ip_clean_pattern'], script_match.group(1))
            elif 'tag' in rule:
                # 提取指定标签中的IP（如pre、div）
                soup = BeautifulSoup(html, "lxml")
                target_tag = soup.find(rule['tag'], attrs=rule['attrs'])
                if target_tag:
                    content = target_tag.get_text()
                    ips = IP_PATTERN.findall(content) + IP_WITH_PORT_PATTERN.findall(content)
        
        # 2. 通用提取（兜底）
        if not ips:
            ips = IP_PATTERN.findall(html) + IP_WITH_PORT_PATTERN.findall(html)
        
        # 3. 过滤无效IP（排除内网IP和格式错误的IP）
        valid_ips = []
        for ip in ips:
            ip_clean = ip.split(":")[0]  # 移除端口
            # 检查是否为内网IP（10.x.x.x、192.168.x.x、172.x.x.x）
            if ip_clean.startswith(("10.", "192.168.", "172.")):
                continue
            # 检查IP格式是否正确（四段数字，每段0-255）
            if len(ip_clean.split(".")) == 4 and all(0 <= int(seg) <= 255 for seg in ip_clean.split(".")):
                valid_ips.append(ip)
        
        logging.info(f"从 {url} 提取到 {len(valid_ips)} 个有效IP")
        return valid_ips

    def crawl(self) -> Set[str]:
        """抓取所有站点的IP并去重"""
        all_ips = set()
        for url in URLS:
            try:
                html = self.fetch_page(url)
                ips = self.extract_ips(html, url)
                all_ips.update(ips)
            except Exception as e:
                logging.error(f"处理 {url} 失败: {e}")
            self._sleep()
        return all_ips

    def save_ips(self, ips: Set[str]):
        """保存IP到文件（确保生成文件）"""
        # 打印IP数量，确认是否有数据
        logging.info(f"待保存的IP总数：{len(ips)} 个")

        # 准备文件内容（空IP则生成空文件）
        if not ips:
            content = ""
            logging.warning("未抓取到有效IP，生成空文件")
        else:
            # 按IP排序
            sorted_ips = sorted(ips, key=lambda x: tuple(map(int, x.split(":")[0].split("."))))
            content = "\n".join(sorted_ips) + "\n"

        # 强制生成文件，捕获权限错误
        try:
            with open(OUTPUT_FILE, "w", encoding="utf8") as f:
                f.write(content)
            # 显示文件保存路径（避免找不到文件）
            file_path = os.path.abspath(OUTPUT_FILE)
            logging.info(f"IP已保存到：{file_path}")
        except Exception as e:
            logging.error(f"保存文件失败！请检查路径权限：{e}")

# ---------- 主程序 ----------
if __name__ == "__main__":
    collector = IPCollector()
    # 抓取IP
    ip_set = collector.crawl()
    # 保存IP（无论多少，强制生成文件）
    collector.save_ips(ip_set)
