import os
import json
import glob

def remove_display_name(obj):
    """
    递归遍历并删除字典中名为 'display_name' 的键
    """
    if isinstance(obj, dict):
        if 'display_name' in obj:
            del obj['display_name']
        for k, v in obj.items():
            remove_display_name(v)
    elif isinstance(obj, list):
        for item in obj:
            remove_display_name(item)

def main():
    print("开始清理冗余配置字段...")
    
    # 1. 处理布局 JSON 文件夹
    data_dir = r"d:\Documents\Code\ai\layout-rag\data\layouts"
    json_files = glob.glob(os.path.join(data_dir, "*.json"))
    
    modified_count = 0
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 使用简单的探测避免无效重写
            json_str = json.dumps(data, ensure_ascii=False)
            if "display_name" not in json_str:
                continue
                
            remove_display_name(data)
            
            # 重写内容
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            
            modified_count += 1
        except Exception as e:
            print(f"写入文件失败 {file_path}: {e}")

    print(f"成功: 已从 {modified_count} 个元件 JSON 文件中成功移除 'display_name'。")

    # 2. 处理已构建的本地向量库 (如果它包含特征字典)
    vec_file = r"d:\Documents\Code\ai\layout-rag\vecdb\vector_store.json"
    if os.path.exists(vec_file):
        try:
            with open(vec_file, "r", encoding="utf-8") as f:
                vec_data = json.load(f)
            
            json_str = json.dumps(vec_data, ensure_ascii=False)
            if "display_name" in json_str:
                remove_display_name(vec_data)
                with open(vec_file, "w", encoding="utf-8") as f:
                    # 对于 vector_store 可能非常大，避免缩进导致文件剧增
                    json.dump(vec_data, f, ensure_ascii=False)
                print(f"成功: 已清理向量库缓存文件 vector_store.json。")
        except Exception as e:
            print(f"清理 vector_store 失败: {e}")

if __name__ == "__main__":
    main()
