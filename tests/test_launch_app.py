import os
import json
import base64
import subprocess
import sys

def test_launch_electron():
    # 1. 配置文件路径
    json_path = os.path.abspath(r"electron-app/testdata.json")
    # 优先检查打包后的 exe，如果没有则使用 npm start
    exe_path = os.path.abspath(r"electron-app/dist/win-unpacked/Layout RAG Client.exe")
    
    if not os.path.exists(json_path):
        print(f"错误: 找不到测试数据文件: {json_path}")
        return

    # 2. 获取路径
    abs_input_path = os.path.abspath(json_path)
    abs_output_path = os.path.abspath("last_layout_result.json")
    print(f"输入路径: {abs_input_path}")
    print(f"输出路径: {abs_output_path}")

    # 4. 启动 Electron 并捕获输出
    print("\n[测试脚本] 正在启动应用，等待结果返回...")
    
    cmd = []
    if os.path.exists(exe_path):
        cmd = [exe_path, abs_input_path, abs_output_path]
        # 使用 Popen 启动并捕获输出
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    else:
        print("未检测到打包后的 EXE，尝试通过 'npm start' (开发模式) 启动...")
        electron_app_dir = os.path.abspath("electron-app")
        # 注意：npm start 传参需要额外的 -- 分隔符
        process = subprocess.Popen(f'npm start -- "{abs_input_path}" "{abs_output_path}"', shell=True, cwd=electron_app_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')

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

    # 等待进程完全退出
    exit_code = process.wait()
    
    if exit_code == 0:
        print("\n" + "="*50)
        print("【✅ 方案已应用】用户点击了应用按钮。")
        if os.path.exists(abs_output_path):
            with open(abs_output_path, 'r', encoding='utf-8') as f:
                res_json = json.load(f)
            print(f"结果文件: {abs_output_path}")
            print(f"元件总数: {len(res_json.get('schema', {}).get('parts', []))}")
        print("="*50)
    elif exit_code == 2:
        print("\n" + "="*50)
        print("【⚠️ 操作取消】用户直接关闭了窗口。")
        print("未生成或更新结果文件。")
        print("="*50)
    else:
        print(f"\n【❌ 异常退出】状态码: {exit_code}")
        # 打印 stderr 方便调试
        err_out = process.stderr.read()
        if err_out:
            print(f"错误详情: {err_out}")

    print("\n[测试脚本] 测试结束。")

if __name__ == "__main__":
    test_launch_electron()
