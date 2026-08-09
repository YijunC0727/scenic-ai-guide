import os
# 环境变量
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
from huggingface_hub import snapshot_download
repo = "BAAI/bge-small-zh-v1.5"
current_dir = os.getcwd()
save_path = os.path.join(current_dir, "bge-small-zh-v1.5")
snapshot_download(
    repo_id=repo,
    local_dir=save_path,
    resume_download=True
)
print("下载完成")