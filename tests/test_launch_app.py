import os
import json
import base64
import subprocess
import sys

def test_launch_electron():
    # 1. 配置文件路径
    json_path = os.path.abspath(r"electron-app/testdata.json")
    # 优先检查打包后的 exe，如果没有则使用 npm start
    exe_path = os.path.abspath(r"electron-app/dist/Layout RAG Client-win32-x64/Layout RAG Client.exe")
    
    if not os.path.exists(json_path):
        print(f"错误: 找不到测试数据文件: {json_path}")
        return

    # 2. 读取 JSON 内容
    print(f"正在读取数据: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 3. 转换为 Base64
    json_str = json.dumps(data)
    base64_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    print("数据 Base64 编码完成。")

    # 4. 启动 Electron 并捕获输出
    print("\n[测试脚本] 正在启动应用，等待结果返回...")
    
    cmd = []
    if os.path.exists(exe_path):
        cmd = [exe_path, base64_data]
        # 使用 Popen 启动并捕获输出
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    else:
        print("未检测到打包后的 EXE，尝试通过 'npm start' (开发模式) 启动...")
        electron_app_dir = os.path.abspath("electron-app")
        process = subprocess.Popen(f'npm start -- "{base64_data}"', shell=True, cwd=electron_app_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')

    # 5. 监听 stdout
    while True:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                break
            continue
        
        line = line.strip()
        # 打印原始输出方便调试
        if line:
            print(f"  [App Output] {line}")

        # 检查是否有结果数据前缀
        if line.startswith("RESULT_DATA:"):
            b64_res = line.replace("RESULT_DATA:", "").strip()
            try:
                res_json = json.loads(base64.b64decode(b64_res).decode('utf-8'))
                print("\n" + "="*50)
                print("【成功接收到布局结果！】")
                print(f"包含元件数量: {len(res_json.get('schema', {}).get('parts', []))}")
                print(f"结果预览 (前100字符): {json.dumps(res_json, ensure_ascii=False)[:100]}...")
                print("="*50)
                
                # 保存结果到本地文件
                # output_file = "last_layout_result.json"
                # with open(output_file, "w", encoding="utf-8") as out_f:
                #     json.dump(res_json, out_f, indent=2, ensure_ascii=False)
                # print(f"结果已保存至: {os.path.abspath(output_file)}")
                break
            except Exception as e:
                print(f"解析结果失败: {e}")

    # 等待进程完全退出
    process.wait()
    print("\n[测试脚本] 应用已退出。")

if __name__ == "__main__":
    test_launch_electron()
