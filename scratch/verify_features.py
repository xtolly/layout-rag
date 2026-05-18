import sys
import os

# 将 src 目录添加到 Python 路径
sys.path.append(os.path.join(os.getcwd(), 'src'))

from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain

def test_extract_features_with_inline_parts():
    domain = NewDistributionBoxDomain()
    
    layout_json = {
        "schema": {
            "parts": [
                {
                    "part_type": "微型断路器",
                    "part_size": [60, 80],
                    "in_line": True
                },
                {
                    "part_type": "微型断路器",
                    "part_size": [60, 80],
                    "in_line": False
                },
                {
                    "part_type": "指示灯",
                    "part_size": [20, 20],
                    "in_line": True
                }
            ]
        }
    }
    
    features = domain.extract_features(layout_json)
    
    print(f"Features: {features}")
    
    # 验证进线元件数量：1个微型断路器 + 1个指示灯 = 2
    assert features["inline_parts_count"] == 2
    
    # 验证进线元件面积：(60*80) + (20*20) = 4800 + 400 = 5200
    assert features["inline_parts_area"] == 5200.0
    
    # 验证总元件数量
    assert features["total_parts"] == 3
    print("Test passed!")

if __name__ == "__main__":
    try:
        test_extract_features_with_inline_parts()
    except Exception as e:
        print(f"Test failed: {e}")
        sys.exit(1)
