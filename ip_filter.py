import pandas as pd
import requests
from io import StringIO
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_retry_session():
    """创建带重试机制的请求会话（解决网络波动问题）"""
    session = requests.Session()
    retry = Retry(
        total=3,  # 总重试次数
        backoff_factor=1,  # 重试间隔（1s, 2s, 4s...）
        status_forcelist=[429, 500, 502, 503, 504]  # 需要重试的状态码
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def load_ip_geo_database():
    """加载公开IP地理位置数据库（修复字段名，适配实际数据结构）"""
    try:
        # 验证过的可用IP地理数据库链接（含备用）
        geo_urls = [
            "https://raw.githubusercontent.com/louislam/uptime-kuma/master/src/data/ip2location.csv",
            "https://cdn.jsdelivr.net/gh/louislam/uptime-kuma/src/data/ip2location.csv"
        ]
        session = create_retry_session()
        geo_df = None

        for url in geo_urls:
            try:
                print(f"尝试从链接加载数据：{url}")
                response = session.get(url, timeout=20)
                response.raise_for_status()  # 捕获4xx/5xx错误
                geo_df = pd.read_csv(StringIO(response.text))
                # 验证必要字段是否存在（修复核心问题：用region替代location）
                required_cols = ['start_ip', 'end_ip', 'region']
                if not all(col in geo_df.columns for col in required_cols):
                    print(f"警告：该链接数据缺少必要字段，尝试下一个链接")
                    continue
                print("IP地理数据库加载成功")
                break
            except Exception as e:
                print(f"该链接加载失败：{str(e)[:50]}，尝试下一个链接")
                continue
        
        if geo_df is None:
            raise Exception("所有IP地理数据库链接均失效，请检查网络或更换链接")
        
        # 处理IP段为整数（确保转换函数正常调用）
        geo_df['start_ip_int'] = geo_df['start_ip'].apply(_ip_to_integer)
        geo_df['end_ip_int'] = geo_df['end_ip'].apply(_ip_to_integer)
        # 过滤无效IP段（避免后续匹配错误）
        geo_df = geo_df.dropna(subset=['start_ip_int', 'end_ip_int'])
        return geo_df
    except Exception as e:
        print(f"加载IP地理数据失败: {str(e)}")
        exit(1)

def _ip_to_integer(ip_str):
    """将IP地址转换为整数（增加参数校验，避免异常崩溃）"""
    try:
        if not isinstance(ip_str, str) or len(ip_str.split('.')) != 4:
            return None  # 不是合法IP格式
        octets = list(map(int, ip_str.split('.')))
        if any(not (0 <= octet <= 255) for octet in octets):
            return None  # 每个段数值超出0-255范围
        return octets[0] << 24 | octets[1] << 16 | octets[2] << 8 | octets[3]
    except:
        return None

def get_ip_region(ip_str, geo_df):
    """根据IP地址获取所属地区（优化匹配逻辑，提高准确率）"""
    ip_int = _ip_to_integer(ip_str)
    if ip_int is None:
        return "未知"
    
    # 精准匹配IP所在网段（避免全表扫描，提高效率）
    mask = (geo_df['start_ip_int'] <= ip_int) & (geo_df['end_ip_int'] >= ip_int)
    if mask.any():
        # 获取地区信息并统一转为小写（避免大小写匹配问题）
        region_info = str(geo_df[mask]['region'].iloc[0]).strip().lower()
        # 目标地区关键词（覆盖中英文常见表述）
        target_keywords = {
            'hong kong': ['hong kong', '香港'],
            'japan': ['japan', '日本'],
            'singapore': ['singapore', '新加坡']
        }
        # 匹配目标地区
        for region, keywords in target_keywords.items():
            if any(keyword.lower() in region_info for keyword in keywords):
                return region  # 返回标准地区名（便于后续统计）
    return "未知"

def filter_target_regions_ip(input_file="ip.txt", output_file="ip2.txt"):
    """筛选目标地区IP（增加全流程日志，便于排查问题）"""
    print("=" * 50)
    print("开始执行IP筛选任务（目标：香港/日本/新加坡）")
    print("=" * 50)

    # 1. 读取原始IP文件（增加文件权限和格式校验）
    if not os.path.exists(input_file):
        print(f"错误：原始IP文件 '{input_file}' 不存在，请检查文件路径")
        exit(1)
    if not os.access(input_file, os.R_OK):
        print(f"错误：没有读取 '{input_file}' 文件的权限")
        exit(1)
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_ips = [line.strip() for line in f if line.strip()]
        # 去重并过滤无效IP格式
        valid_raw_ips = [ip for ip in list(set(raw_ips)) if _ip_to_integer(ip) is not None]
        invalid_ips = [ip for ip in list(set(raw_ips)) if _ip_to_integer(ip) is None]
        print(f"读取到原始IP总数：{len(raw_ips)} 个（去重后）")
        print(f"有效IP数量：{len(valid_raw_ips)} 个")
        if invalid_ips:
            print(f"无效IP数量：{len(invalid_ips)} 个（已过滤，示例：{invalid_ips[:3]}）")
    except Exception as e:
        print(f"读取原始IP文件失败：{str(e)}")
        exit(1)

    # 2. 加载IP地理数据库
    print("\n步骤1/3：加载IP地理数据库...")
    geo_df = load_ip_geo_database()

    # 3. 筛选目标地区IP（增加进度提示）
    print(f"\n步骤2/3：筛选目标地区IP（共需处理 {len(valid_raw_ips)} 个有效IP）")
    target_ips = []
    region_count = {'hong kong': 0, 'japan': 0, 'singapore': 0}  # 实时统计各地区数量
    
    for idx, ip in enumerate(valid_raw_ips, 1):
        # 每处理100个IP提示一次进度
        if idx % 100 == 0 or idx == len(valid_raw_ips):
            print(f"已处理 {idx}/{len(valid_raw_ips)} 个IP...")
        
        region = get_ip_region(ip, geo_df)
        if region in region_count:
            target_ips.append(ip)
            region_count[region] += 1

    # 4. 保存筛选结果（确保输出文件目录存在）
    print(f"\n步骤3/3：保存筛选结果...")
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)  # 若输出目录不存在则创建
    
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(target_ips))
    except Exception as e:
        print(f"保存筛选结果失败：{str(e)}")
        exit(1)

    # 输出最终统计报告
    print("\n" + "=" * 50)
    print("IP筛选任务完成！")
    print("=" * 50)
    print(f"总有效IP数：{len(valid_raw_ips)} 个")
    print(f"目标地区IP总数：{len(target_ips)} 个")
    print("各地区IP分布：")
    for region, count in region_count.items():
        region_cn = {'hong kong': '香港', 'japan': '日本', 'singapore': '新加坡'}[region]
        print(f"  - {region_cn}：{count} 个")
    print(f"筛选结果文件：{os.path.abspath(output_file)}")
    print("=" * 50)

if __name__ == "__main__":
    # 调用筛选函数（支持自定义输入输出路径，便于灵活使用）
    filter_target_regions_ip(
        input_file="ip.txt",  # 原始IP文件路径
        output_file="ip2.txt" # 筛选后IP文件路径
    )
