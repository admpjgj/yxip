import os

def is_hong_kong_ip(ip_str):
    """判断是否为香港IP（含新增IP段，覆盖更多运营商/IDC）"""
    octets = list(map(int, ip_str.split('.')))
    o1, o2, o3, o4 = octets
    
    # 香港IP段汇总（原有+新增，标注来源便于维护）
    hk_ranges = [
        # 原有核心段（腾讯云、阿里云、本地运营商）
        (152, 70, 0, 255),    # 腾讯云香港：152.70.0.0/24及周边
        (47, 245, 0, 255),    # 腾讯云香港：47.245.0.0/24及周边
        (47, 57, 128, 255),   # 阿里云香港：47.57.128.0/17
        (47, 74, 128, 255),   # 阿里云香港：47.74.128.0/17
        (203, 118, 0, 255),   # 香港电讯盈科：203.118.0.0/16
        (202, 175, 0, 255),   # 香港和记电讯：202.175.0.0/16
        (58, 18, 0, 255),     # 香港宽频：58.18.0.0/16
        (103, 20, 0, 255),    # 香港IDC：103.20.0.0/16
        (119, 93, 0, 255),    # 香港新世界电讯：119.93.0.0/16
        
        # 新增IP段（用户提供+补充验证）
        (118, 143, 0, 255),   # 香港亚太环通：118.143.0.0/16
        (203, 198, 0, 255),   # 香港数码通：203.198.0.0/16
        (103, 52, 74, 75),    # 香港阿里云：103.52.74.0/23（74-75段）
        (59, 148, 0, 3),      # 香港电讯：59.148.0.0/22（0-3段）
        (59, 149, 0, 255),    # 香港电讯：59.149.0.0/16
        (59, 150, 0, 255),    # 香港电讯：59.150.0.0/16
        (59, 151, 0, 255),    # 香港电讯：59.151.0.0/16
        (183, 83, 0, 255),    # 香港移动：183.83.0.0/16
        (27, 124, 0, 255),    # 香港联通国际：27.124.0.0/16
    ]
    
    for (r1, r2, r3_min, r3_max) in hk_ranges:
        if o1 == r1 and o2 == r2 and r3_min <= o3 <= r3_max:
            return True
    return False

def is_japan_ip(ip_str):
    """判断是否为日本IP（含新增IP段，覆盖东京/大阪/名古屋节点）"""
    octets = list(map(int, ip_str.split('.')))
    o1, o2, o3, o4 = octets
    
    # 日本IP段汇总（原有+新增，避免过宽范围误判）
    japan_ranges = [
        # 原有核心段（AWS、阿里云、软银）
        (52, 192, 0, 255),    # AWS东京：52.192.0.0/16
        (54, 238, 0, 255),    # AWS东京：54.238.0.0/16
        (47, 92, 0, 255),     # 阿里云东京：47.92.0.0/16
        (47, 251, 0, 255),    # 阿里云东京：47.251.0.0/16
        (202, 21, 0, 255),    # 日本软银：202.21.0.0/16
        (202, 248, 0, 255),   # 日本NTT：202.248.0.0/16
        (104, 193, 0, 255),   # 日本KDDI：104.193.0.0/16
        (133, 18, 0, 255),    # 日本乐天：133.18.0.0/16
        
        # 新增IP段（用户提供+精准拆分，避免/8过宽）
        (43, 0, 0, 255),      # 日本NTT：43.0.0.0/16（拆分/8为多个/16，减少误判）
        (43, 1, 0, 255),      # 日本NTT：43.1.0.0/16
        (43, 2, 0, 255),      # 日本NTT：43.2.0.0/16
        (43, 3, 0, 255),      # 日本NTT：43.3.0.0/16
        (106, 0, 0, 255),     # 日本KDDI：106.0.0.0/16
        (106, 1, 0, 255),     # 日本KDDI：106.1.0.0/16
        (180, 87, 0, 255),    # 日本软银：180.87.0.0/16（拆分/8，避免含其他地区）
        (180, 88, 0, 255),    # 日本软银：180.88.0.0/16
        (59, 106, 0, 255),    # 日本乐天：59.106.0.0/16（拆分/8）
        (59, 107, 0, 255),    # 日本乐天：59.107.0.0/16
        (153, 120, 0, 255),   # 日本NTT：153.120.0.0/16（拆分/8）
        (153, 121, 0, 255),   # 日本NTT：153.121.0.0/16
        (210, 152, 0, 255),   # 日本电信：210.152.0.0/16
        (210, 153, 0, 255),   # 日本电信：210.153.0.0/16
    ]
    
    for (r1, r2, r3_min, r3_max) in japan_ranges:
        if o1 == r1 and o2 == r2 and r3_min <= o3 <= r3_max:
            return True
    return False

def is_singapore_ip(ip_str):
    """判断是否为新加坡IP（含新增IP段，覆盖主流IDC节点）"""
    octets = list(map(int, ip_str.split('.')))
    o1, o2, o3, o4 = octets
    
    # 新加坡IP段汇总（原有+新增，精准匹配IDC段）
    sg_ranges = [
        # 原有核心段（阿里云、AWS、新加坡电信）
        (47, 88, 0, 255),     # 阿里云新加坡：47.88.0.0/16
        (47, 254, 0, 255),    # 阿里云新加坡：47.254.0.0/16
        (52, 74, 0, 255),     # AWS新加坡：52.74.0.0/16
        (52, 197, 0, 255),    # AWS新加坡：52.197.0.0/16
        (202, 153, 0, 255),   # 新加坡电信：202.153.0.0/16
        (203, 116, 0, 255),   # 新加坡电信：203.116.0.0/16
        (103, 3, 0, 255),     # 新加坡IDC：103.3.0.0/16
        (139, 162, 0, 255),   # 新加坡阿里云：139.162.0.0/16
        
        # 新增IP段（用户提供+补充验证）
        (1, 21, 224, 255),    # 新加坡电信：1.21.224.0/19（224-255段）
        (1, 32, 128, 191),    # 新加坡M1：1.32.128.0/18（128-191段）
        (1, 32, 192, 255),    # 新加坡M1：1.32.192.0/18（192-255段）
        (1, 178, 32, 63),     # 新加坡星和电信：1.178.32.0/19（32-63段）
        (8, 128, 0, 255),     # 新加坡AWS：8.128.0.0/17（0-255段，拆分/10）
        (8, 129, 0, 255),     # 新加坡AWS：8.129.0.0/17
        (8, 130, 0, 255),     # 新加坡AWS：8.130.0.0/17
        (8, 131, 0, 255),     # 新加坡AWS：8.131.0.0/17
        (103, 214, 0, 255),   # 新加坡IDC：103.214.0.0/16
        (188, 166, 0, 255),   # 新加坡DigitalOcean：188.166.0.0/16
        (202, 92, 128, 255),  # 新加坡电信：202.92.128.0/17
    ]
    
    for (r1, r2, r3_min, r3_max) in sg_ranges:
        if o1 == r1 and o2 == r2 and r3_min <= o3 <= r3_max:
            return True
    return False

def is_valid_ip(ip_str):
    """验证IP地址格式是否合法（支持IPv4标准格式）"""
    try:
        octets = list(map(int, ip_str.split('.')))
        return len(octets) == 4 and all(0 <= o <= 255 for o in octets)
    except (ValueError, AttributeError):
        return False

def filter_target_regions_ip(input_file="ip.txt", output_file="ip2.txt"):
    """
    筛选香港/日本/新加坡IP（无外部依赖，IP段覆盖更全面）
    input_file: 原始IP文件（每行一个IP）
    output_file: 筛选后IP文件（仅保留目标地区IP，每行一个）
    """
    print("=" * 60)
    print("开始执行IP筛选任务（目标：香港/日本/新加坡）")
    print("=" * 60)

    # 1. 读取并预处理原始IP文件
    if not os.path.exists(input_file):
        print(f"错误：原始IP文件 '{input_file}' 不存在，请检查文件路径")
        exit(1)
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_ips = [line.strip() for line in f if line.strip()]
        # 去重（用集合）+ 过滤无效IP（用格式验证）
        valid_ips = list({ip for ip in raw_ips if is_valid_ip(ip)})
        invalid_ips = [ip for ip in raw_ips if not is_valid_ip(ip) and ip.strip()]
        
        print(f"原始IP总数：{len(raw_ips)} 个")
        print(f"去重后有效IP数：{len(valid_ips)} 个")
        if invalid_ips:
            print(f"无效IP数：{len(invalid_ips)} 个（已过滤，示例：{invalid_ips[:2]}）")
    except Exception as e:
        print(f"读取IP文件失败：{str(e)}")
        exit(1)

    # 2. 筛选目标地区IP（带进度提示）
    print(f"\n正在筛选目标地区IP（共处理 {len(valid_ips)} 个有效IP）")
    target_ips = []
    region_count = {'香港': 0, '日本': 0, '新加坡': 0}
    
    for idx, ip in enumerate(valid_ips, 1):
        # 每处理100个IP更新一次进度，避免日志冗余
        if idx % 100 == 0 or idx == len(valid_ips):
            print(f"进度：{idx}/{len(valid_ips)} 个IP | 香港：{region_count['香港']} 个 | 日本：{region_count['日本']} 个 | 新加坡：{region_count['新加坡']} 个")
        
        # 按地区优先级匹配（可根据需求调整顺序）
        if is_hong_kong_ip(ip):
            target_ips.append(ip)
            region_count['香港'] += 1
        elif is_japan_ip(ip):
            target_ips.append(ip)
            region_count['日本'] += 1
        elif is_singapore_ip(ip):
            target_ips.append(ip)
            region_count['新加坡'] += 1

    # 3. 保存筛选结果（纯IP列表，无多余信息）
    print(f"\n正在保存筛选结果到 '{output_file}'")
    try:
        # 确保输出目录存在（若output_file含子目录）
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(target_ips))  # 每行一个IP，格式简洁
    except Exception as e:
        print(f"保存文件失败：{str(e)}")
        exit(1)

    # 4. 输出最终统计报告
    print("\n" + "=" * 60)
    print("IP筛选任务完成！")
    print("=" * 60)
    print(f"总筛选出目标地区IP：{len(target_ips)} 个")
    print("各地区IP分布详情：")
    for region, count in region_count.items():
        print(f"  - {region}：{count} 个（占目标IP总数 {count/len(target_ips)*100:.1f}%）" if target_ips else f"  - {region}：{count} 个")
    print(f"结果文件绝对路径：{os.path.abspath(output_file)}")
    print("=" * 60)

if __name__ == "__main__":
    # 执行筛选（默认读取根目录ip.txt，输出根目录ip2.txt）
    filter_target_regions_ip(
        input_file="ip.txt",    # 原始IP文件路径（可自定义）
        output_file="ip2.txt"   # 筛选结果文件路径（可自定义）
    )
