#!/bin/bash
# ============================================
#  Lio 摄影作品集 - 一键部署脚本
# ============================================
#  用法:  ./deploy.sh
#  流程:  扫描图片 → 生成缩略图 → git提交 → 推送 → Vercel自动部署
# ============================================

set -e

cd "$(dirname "$0")"
echo "📷  Lio Photo Portfolio - Deploy"
echo "=================================="

# 1. 生成缩略图 + gallery.json
echo ""
echo "→ 1/3 扫描图片并生成缩略图..."
python3 generate_gallery.py

# 2. 检查 git 是否已初始化
if [ ! -d ".git" ]; then
    echo ""
    echo "→ 首次运行，初始化 Git..."
    git init
    git remote add origin https://github.com/Liooo0/lio-photo-portfolio.git
    git branch -M main
fi

# 3. 提交并推送
echo ""
echo "→ 2/3 提交更改..."
git add -A
git commit -m "📷 $(date '+%Y-%m-%d %H:%M') - 更新作品集" || echo "  (没有新的更改)"

echo ""
echo "→ 3/3 推送到 GitHub..."
git push -u origin main

echo ""
echo "=================================="
echo "✅ 部署完成！"
echo "   等 1-2 分钟后访问: https://lio-photo-portfolio.vercel.app"
echo "=================================="
