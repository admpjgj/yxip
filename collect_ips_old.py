import requests
from bs4 import BeautifulSoup
import re
import os
import geoip2.database

# 目标URL列表
urls = ['https://www.wetest.vip/page/cloudflare/address_v4.html', 
        'https://ip.164746.xyz']

# 正则表达式用于匹配IP地址
ip_pattern = r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'

# 筛选IP的目标国家
target_countries = ['US', 'SG', 'JP', 'HK']  # 美国、新加坡、日本、香港

# GeoLite2数据库路径（你需要下载GeoLite2-Country.mmdb）
geoip_db_path = 'GeoLite2-Country.mmdb'

# 检查ip.txt文件是否存在, 如果存在则删除它
if os.path.exists('ip.txt'):
    os.remove('ip.txt')

# 创建GeoIP读取器
reader = geoip2.database.Reader(geoip_db_path)

# 创建一个文件来存储IP地址
with open('ip.txt', 'w') as file:
    for url in urls:
        try:
            # 发送HTTP请求获取网页内容
            response = requests.get(url)
            response.raise_for_status()  # 如果状态码不是200，会抛出异常
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {url}，错误信息: {e}")
            continue  # 跳过该URL，继续下一个
        
        # 使用BeautifulSoup解析HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 根据网站的不同结构找到包含IP地址的元素
        if url == 'https://www.wetest.vip/page/cloudflare/address_v4.html':
            elements = soup.find_all('tr')
        elif url == 'https://ip.164746.xyz':
            elements = soup.find_all('tr')
        else:
            elements = soup.find_all('li')
        
        # 遍历所有元素, 查找IP地址
        for element in elements:
            element_text = element.get_text()
            ip_matches = re.findall(ip_pattern, element_text)
            
            # 对每个匹配的IP，查询地理位置信息
            for ip in ip_matches:
                try:
                    # 使用GeoIP2查询IP的地理信息
                    response = reader.country(ip)
                    country_code = response.country.iso_code
                    if country_code in target_countries:
                        # 如果IP地址属于目标国家，写入文件
                        file.write(ip + '\n')
                except geoip2.errors.AddressNotFoundError:
                    print(f"IP {ip} 不在数据库中")
                    continue  # 如果IP不在数据库中，跳过
                
print('筛选后的IP地址已保存到ip.txt文件中。')

# 关闭数据库读取器
reader.close()
