@echo off
chcp 65001 >nul
cd /d "%~dp0/.."
echo ==============================================
echo          RAG端侧一键启动脚本 Windows
echo ==============================================

::检查Python3.12
python --version | findstr "3.12" >nul
if %errorlevel% neq 0 (
    echo ❌【失败】未检测到 Python3.12，请先安装并加入系统环境变量。如果确定Python版本可以跑的话，修改3.12为自己的版本就可以
    pause
    exit /b 1
)
echo ✅ Python3.12 校验通过

::创建虚拟环境
if not exist venv (
    echo 正在创建venv虚拟环境...
    python -m venv venv
)
echo ✅ venv环境就绪

::激活环境，升级pip，安装依赖
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo 正在安装requirements.txt依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo ❌【失败】依赖包安装失败！检查是否有requirements.txt或网络。
    pause
    exit /b 2
)
echo ✅ 全部依赖安装完成

::校验离线资源，和任务2打包输出对应
if not exist scripts\bge-small-zh-v1.5 (
    echo ❌【失败】缺失BGE模型 scripts\bge-small-zh-v1.5\
    pause
    exit /b 3
)
if not exist chroma_db (
    echo ❌【失败】缺失Chroma向量库 chroma_db\
    pause
    exit /b 3
)
echo ✅ 离线资源校验通过

echo.
echo  开始启动RAG服务（FastAPI，默认 0.0.0.0:8000）
echo ==============================================
python scripts\api_server.py
pause
