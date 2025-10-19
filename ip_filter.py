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
    """加载IP2Location官方轻量数据库（稳定可用，替换原404链接）"""
    try:
        # 替换为IP2Location官方公开数据库（支持地区识别，稳定维护）
        # 数据库说明：https://www.ip2location.com/free/ip2location-lite
        geo_urls = [
            "https://raw.githubusercontent.com/ip2location/IP2Location-CSV/master/IP2LOCATION-LITE-DB3.CSV",
            "https://cdn.jsdelivr.net/gh/ip2location/IP2Location-CSV@master/IP2LOCATION-LITE-DB3.CSV"
        ]
        session = create_retry_session()
        geo_df = None

        for url in geo_urls:
            try:
                print(f"尝试从链接加载IP数据库：{url}")
                response = session.get(url, timeout=30)  # 延长超时时间（数据库约2MB）
                response.raise_for_status()
                
                # 解析IP2Location DB3格式（字段：start_ip, end_ip, country_code, country_name, region, city）
                # 跳过首行注释，指定字段名
                geo_df = pd.read_csv(
                    StringIO(response.text),
                    skiprows=1,  # 跳过首行说明注释
                    names=['start_ip', 'end_ip', 'country_code', 'country_name', 'region', 'city'],
                    dtype=str  # 避免IP段被自动转为科学计数法
                )
                
                # 验证必要字段
                required_cols = ['start_ip', 'end_ip', 'region']
                if not all(col in geo_df.columns for col in required_cols):
                    print(f"警告：数据库字段不完整，尝试下一个链接")
                    continue
                
                print("IP地理数据库加载成功（IP2Location DB3）")
                break
            except Exception as e:
                error_msg = str(e)[:60] + "..." if len(str(e)) > 60 else str(e)
                print(f"该链接加载失败：{error_msg}，尝试下一个链接")
                continue
        
        if geo_df is None:
            raise Exception("所有IP数据库链接均失效，建议检查网络或手动下载数据库")
        
        # 处理IP段：将IP段（如"1.0.0.0"）转为整数，便于匹配
        geo_df['start_ip_int'] = geo_df['start_ip'].apply(_ip_to_integer)
        geo_df['end_ip_int'] = geo_df['end_ip'].apply(_ip_to_integer)
        
        # 过滤无效数据（移除IP段转换失败的行）
        geo_df = geo_df.dropna(subset=['start_ip_int', 'end_ip_int'])
        geo_df = geo_df[geo_df['start_ip_int'] <= geo_df['end_ip_int']]  # 过滤逻辑错误的IP段
        
        print(f"有效IP网段数量：{len(geo_df)} 个")
        return geo_df
    except Exception as e:
        print(f"加载IP数据库失败: {str(e)}")
        exit(1)

def _ip_to_integer(ip_str):
    """将IP地址转换为整数（支持IP段格式，增加容错）"""
    try:
        if not isinstance(ip_str, str) or len(ip_str.split('.')) != 4:
            return None
        octets = list(map(int, ip_str.split('.')))
        if any(not (0 <= octet <= 255) for octet in octets):
            return None
        return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
    except:
        return None

def get_ip_region(ip_str, geo_df):
    """根据IP匹配地区（适配IP2Location DB3格式，提高识别准确率）"""
    ip_int = _ip_to_integer(ip_str)
    if ip_int is None:
        return "未知"
    
    # 高效匹配IP所在网段（利用IP段有序性，减少计算量）
    # 先筛选可能的网段（start_ip_int <= 当前IP），再取最后一个满足end_ip_int >= 当前IP的
    candidate_df = geo_df[geo_df['start_ip_int'] <= ip_int].tail(1)
    if not candidate_df.empty and candidate_df.iloc[0]['end_ip_int'] >= ip_int:
        region = str(candidate_df.iloc[0]['region']).strip().lower()
        country = str(candidate_df.iloc[0]['country_name']).strip().lower()
        
        # 识别目标地区（结合国家和地区双重判断，避免误判）
        if any(keyword in country for keyword in ['hong kong', '香港']):
            return 'hong kong'
        elif any(keyword in country for keyword in ['japan', '日本']):
            return 'japan'
        elif any(keyword in country for keyword in ['singapore', '新加坡']):
            return 'singapore'
    
    return "未知"

def filter_target_regions_ip(input_file="ip.txt", output_file="ip2.txt"):
    """筛选目标地区IP（香港/日本/新加坡）"""
    print("=" * 60)
    print("开始执行IP筛选任务（目标：香港/日本/新加坡）")
    print("=" * 60)

    # 1. 读取原始IP文件
    if not os.path.exists(input_file):
        print(f"错误：原始IP文件 '{input_file}' 不存在")
        exit(1)
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_ips = [line.strip() for line in f if line.strip()]
        # 去重+过滤无效IP
        valid_ips = [ip for ip in list(set(raw_ips)) if _ip_to_integer(ip) is not None]
        invalid_ips = [ip for ip in list(set(raw_ips)) if _ip_to_integer(ip) is None]
        
        print(f"原始IP总数（去重后）：{len(raw_ips)} 个")
        print(f"有效IP数量：{len(valid_ips)} 个")
        if invalid_ips:
            print(f"无效IP数量：{len(invalid_ips)} 个（已过滤，示例：{invalid_ips[:2]}）")
    except Exception as e:
        print(f"读取IP文件失败：{str(e)}")
        exit(1)

    # 2. 加载IP地理数据库
    print(f"\n步骤1/3：加载IP地理数据库（约2MB，耐心等待...）")
    geo_df = load_ip_geo_database()

    # 3. 筛选目标地区IP
    print(f"\n步骤2/3：筛选目标地区IP（共{len(valid_ips)}个有效IP）")
    target_ips = []
    region_count = {'hong kong': 0, 'japan': 0, 'singapore': 0}
    
    for idx, ip in enumerate(valid_ips, 1):
        # 每处理100个IP显示进度
        if idx % 100 == 0 or idx == len(valid_ips):
            print(f"已处理：{idx}/{len(valid_ips)} 个IP（当前匹配：香港{region_count['hong kong']}个，日本{region_count['japan']}个，新加坡{region_count['singapore']}个）")
        
        region = get_ip_region(ip, geo_df)
        if region in region_count:
            target_ips.append(ip)
            region_count[region] += 1

    # 4. 保存筛选结果
    print(f"\n步骤3/3：保存筛选结果到 {output_file}")
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(target_ips))  # 仅保存IP，无其他内容
    except Exception as e:
        print(f"保存文件失败：{str(e)}")
        exit(1)

    # 输出最终报告
    print("\n" + "=" * 60)
    print("IP筛选任务完成！")
    print("=" * 60)
    print(f"筛选结果：共 {len(target_ips)} 个目标地区IP")
    print("各地区分布：")
    print(f"  香港：{region_count['hong kong']} 个")
    print(f"  日本：{region_count['japan']} 个")
    print(f"  新加坡：{region_count['singapore']} 个")
    print(f"结果文件路径：{os.path.abspath(output_file)}")
    print("=" * 60)

if __name__ == "__main__":
    filter_target_regions_ip(
        input_file="ip.txt",
        output_file="ip2.txt"
    )
