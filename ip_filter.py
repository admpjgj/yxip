import pandas as pd
import requests
from io import StringIO
import os

def load_ip_geo_database():
    """加载公开IP地理位置数据库（用于识别IP所属地区）"""
    try:
        # 调用公开IP地理数据库（备用链接防止失效）
        geo_urls = [
            "https://raw.githubusercontent.com/louislam/uptime-kuma/master/src/data/ip2location.csv",
            "https://cdn.jsdelivr.net/gh/louislam/uptime-kuma/src/data/ip2location.csv"
        ]
        geo_df = None
        for url in geo_urls:
            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                geo_df = pd.read_csv(StringIO(response.text))
                break
            except:
                continue
        
        if geo_df is None:
            raise Exception("所有IP地理数据库链接均失效")
        
        # 处理IP段为整数（便于后续比较）
        geo_df['start_ip_int'] = geo_df['start_ip'].apply(_ip_to_integer)
        geo_df['end_ip_int'] = geo_df['end_ip'].apply(_ip_to_integer)
        return geo_df
    except Exception as e:
        print(f"加载IP地理数据失败: {str(e)}")
        exit(1)

def _ip_to_integer(ip_str):
    """将IP地址转换为整数（如 192.168.1.1 → 3232235777）"""
    try:
        octets = list(map(int, ip_str.split('.')))
        return octets[0] << 24 | octets[1] << 16 | octets[2] << 8 | octets[3]
    except:
        return None

def get_ip_region(ip_str, geo_df):
    """根据IP地址获取所属地区（仅识别香港/日本/新加坡）"""
    ip_int = _ip_to_integer(ip_str)
    if ip_int is None:
        return "未知"
    
    # 匹配IP所在的网段
    mask = (geo_df['start_ip_int'] <= ip_int) & (geo_df['end_ip_int'] >= ip_int)
    if mask.any():
        location = str(geo_df[mask]['location'].iloc[0]).lower()
        # 识别目标地区（支持中英文匹配）
        target_keywords = ['hong kong', 'japan', 'singapore', '香港', '日本', '新加坡']
        for keyword in target_keywords:
            if keyword.lower() in location:
                return location
    return "未知"

def filter_target_regions_ip(input_file="ip.txt", output_file="ip2.txt"):
    """
    筛选目标地区IP（香港/日本/新加坡）
    input_file: 原始IP文件（每行一个IP）
    output_file: 筛选后IP文件（仅保留目标地区IP）
    """
    # 1. 读取原始IP文件
    if not os.path.exists(input_file):
        print(f"错误：原始IP文件 {input_file} 不存在")
        exit(1)
    
    with open(input_file, 'r', encoding='utf-8') as f:
        raw_ips = [line.strip() for line in f if line.strip()]
    raw_ips = list(set(raw_ips))  # 去重
    print(f"读取到原始IP数量：{len(raw_ips)} 个（已去重）")

    # 2. 加载IP地理数据库
    print("正在加载IP地理数据库...")
    geo_df = load_ip_geo_database()

    # 3. 筛选目标地区IP
    print("正在筛选香港/日本/新加坡IP...")
    target_ips = []
    for ip in raw_ips:
        region = get_ip_region(ip, geo_df)
        if region != "未知":
            target_ips.append(ip)
    
    # 4. 保存筛选结果
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(target_ips))
    
    print(f"筛选完成！目标地区IP数量：{len(target_ips)} 个")
    print(f"结果已保存到：{output_file}")

if __name__ == "__main__":
    filter_target_regions_ip()
